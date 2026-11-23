"""Owner-authored fixed SHA source staging: synthetic no-service contracts."""
from pathlib import Path
import os
import shutil
import stat
from types import SimpleNamespace

import pytest

from scripts import m1_foundation_tunnel_stage as stage
from scripts import m1_foundation_tunnel as tunnel


def event(*, author=stage.OWNER, title=stage.TITLE, body=stage.BODY):
    issue = {"number": 444, "state": "open", "title": title, "body": body,
             "user": {"login": author}}
    return {"action": "opened", "repository": {"full_name": stage.REPO},
            "issue": issue}


def test_fixed_owner_event_refuses_change_and_impersonation():
    request = event()
    assert stage.fixed_request(request, dict(request["issue"])) == 444
    for bad in [event(author="other"),
                event(body=stage.BODY + " extra"),
                event(title="Foundation M1 Tunnel Stage: shell"),
                {**request, "action": "edited"}]:
        with pytest.raises(stage.StageDenied):
            stage.fixed_request(bad, dict(bad["issue"]))
    altered = dict(request["issue"], body="edited")
    with pytest.raises(stage.StageDenied):
        stage.fixed_request(request, altered)


def test_private_stage_has_fixed_zero_effects_and_preserves_owner_branch(
        tmp_path, monkeypatch):
    sha = "a" * 40
    root = tmp_path / "trusted-main"
    owner = tmp_path / "owner"
    repo = owner / "Develop" / "AI-Foundation"
    repo.mkdir(parents=True)
    root.mkdir()
    for name in stage.REQUIRED:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("reviewed source")

    monkeypatch.setattr(stage.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(stage.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(stage.os, "getuid", lambda: 501)
    monkeypatch.setattr(stage.os, "geteuid", lambda: 501)
    original_lstat = Path.lstat
    def owner_lstat(self, *args, **kwargs):
        info = original_lstat(self, *args, **kwargs)
        return SimpleNamespace(st_mode=info.st_mode, st_uid=501)
    monkeypatch.setattr(Path, "lstat", owner_lstat)
    monkeypatch.setattr(stage, "private_dir", lambda p: (
        Path(p).mkdir(mode=0o700, parents=True, exist_ok=True) or Path(p)))

    calls = []
    def git(where, *args, timeout=40):
        calls.append((str(where), args))
        if args == ("rev-parse", "HEAD"):
            return sha
        if args[0] == "status":
            return ""
        if args == ("rev-parse", "--show-toplevel"):
            return str(repo)
        if args[:2] == ("cat-file", "-t"):
            return "commit"
        if args[:3] == ("worktree", "add", "--detach"):
            target = Path(args[3])
            target.mkdir()
            for name in stage.REQUIRED:
                f = target / name
                f.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / name, f)
            return ""
        raise AssertionError(args)
    first = stage.stage_source(checkout=root, home=owner, git=git)
    assert first["status"] == "SOURCE_STAGED_VERIFIED"
    assert first["revision"] == sha
    assert first["model_calls"] == first["native_effects"] == 0
    assert first["operator_changed"] is first["klm_changed"] is False
    assert first["tunnel_started"] is first["remote_client_verified"] is False
    assert sum(args[:2] == ("worktree", "add") for _, args in calls) == 1
    second = stage.stage_source(checkout=root, home=owner, git=git)
    assert second == first
    assert sum(args[:2] == ("worktree", "add") for _, args in calls) == 1
    assert (repo / "scripts").exists() is False


def test_versioned_owner_source_is_preferred_for_tunnel(monkeypatch, tmp_path):
    sha = "b"*40
    stage_root = tmp_path / ".ai-foundation-tunnel-sources" / sha
    stage_root.mkdir(parents=True)
    original_uid = os.getuid()
    monkeypatch.setattr(tunnel.os, "getuid", lambda: original_uid)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    def run(args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=sha+"\n")
    monkeypatch.setattr(tunnel.subprocess, "run", run)
    assert tunnel._installed_source(tmp_path / "CI") == stage_root
    stage_root.rename(stage_root.parent / "altered")
    assert tunnel._installed_source(tmp_path / "CI") == tmp_path / "Develop" / "AI-Foundation"


def test_staging_workflow_is_distinct_from_readonly_bridge():
    repo = Path(__file__).resolve().parents[1]
    workflow = (repo / ".github/workflows/m1-foundation-tunnel-source-stage.yml").read_text()
    diagnostic = (repo / ".github/workflows/m1-development-bridge.yml").read_text()
    assert "github.event.issue.title == 'Foundation M1 Tunnel Stage: source-only'" in workflow
    assert "github.event.issue.user.login == 'quest7070-debug'" in workflow
    assert "persist-credentials: false" in workflow
    assert "scripts/m1_foundation_tunnel_stage.py" in workflow
    assert "Foundation M1 Tunnel Stage: source-only" not in diagnostic
