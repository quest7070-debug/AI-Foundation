"""Synthetic only: one-worker Guard release and exact no-9B admission scope."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import os

import pytest

from scripts import m1_local9b_admission_release as release


def fixed_event():
    event = {
        "action": "labeled", "sender": {"login": release.OWNER},
        "repository": {"full_name": release.REPO},
        "label": {"name": release.LABEL},
        "pull_request": {
            "number": release.PR, "state": "open",
            "user": {"login": release.OWNER},
            "head": {"sha": "f" * 40, "ref": release.BRANCH,
                     "repo": {"full_name": release.REPO}},
        },
    }
    env = {"GITHUB_REPOSITORY": release.REPO,
           "GITHUB_WORKFLOW": release.WORKFLOW,
           "GITHUB_EVENT_NAME": "pull_request",
           "GITHUB_ACTOR": release.OWNER,
           "RELEASE_HANDLER_SHA": "e" * 40}
    return event, env


def fake_api(method, path, token, body=None):
    if path.endswith("/pulls/561"):
        return {"state": "open", "head": {
            "sha": "f" * 40, "ref": release.BRANCH}}
    return [{"name": release.LABEL}]


def test_only_exact_owner_pr_label_cannot_be_client_prose():
    event, env = fixed_event()
    git_calls = [
        SimpleNamespace(returncode=0, stdout="e" * 40 + "\n"),
        SimpleNamespace(returncode=0, stdout=release.CANDIDATE + "\n"),
    ]
    with patch.object(release, "github", fake_api), \
         patch.object(release.subprocess, "run", side_effect=git_calls):
        assert release.owner_event(event, env, "fixture") == "f" * 40
    for mode in ("event-label", "event-sender", "actor", "branch"):
        altered, vars = fixed_event()
        if mode == "event-label":
            altered["label"]["name"] = "any"
        elif mode == "event-sender":
            altered["sender"]["login"] = "untrusted"
        elif mode == "actor":
            vars["GITHUB_ACTOR"] = "untrusted"
        else:
            altered["pull_request"]["head"]["ref"] = "unknown"
        with pytest.raises(release.Denied):
            release.owner_event(altered, vars, "fixture")


def test_candidate_only_changes_worker_import_boundary():
    candidate = (Path(__file__).resolve().parents[1]
                 / "scripts/m1_local9b_admission_candidate.py").read_text()
    assert 'from local9b_worker_paths import configure_worker_paths' in candidate
    assert 'AI_FOUNDATION_LOCAL9B_STATE_ROOT' in candidate
    assert 'from ai_foundation.klm_compute_admission import' in candidate
    assert 'names=subprocess.check_output(["ps","-axo","comm="]' not in candidate
    assert 'SHARED_MODEL_RESIDENT' in candidate
    assert 'ensure_backend_port_available()' in candidate
    assert 'daemon.terminate()' in candidate  # only owned 11436, not shared


def test_release_scope_is_new_and_sole_worker():
    scope = release.scope()
    assert scope.scope_ref == release.scope().scope_ref
    assert release.OLD_WORKER in scope.previous_authority
    assert release.OLD_WORKER_PLIST in scope.previous_authority
    assert release.WORKER_LABEL in scope.previous_endpoint
    assert "OPERATOR" not in scope.switch_target
    assert "RESTORE_EXACT_WORKER_PLIST" in scope.rollback_procedure


def test_one_worker_failure_restores_identical_plist_no_model(tmp_path, monkeypatch):
    plist = tmp_path / "worker.plist"
    plist.write_bytes(b"old")
    old = b"old"
    entry = tmp_path / "old.py"
    proposal = tmp_path / "proposed.plist"
    proposal.write_bytes(b"new")
    prior = (plist, old, {"ProgramArguments": ["/usr/bin/python3", str(entry)]},
             entry, tmp_path, {}, "/tmp/old-inbox")
    monkeypatch.setattr(release, "installed", lambda home: prior)
    monkeypatch.setattr(release, "readback",
                        lambda *args: (_ for _ in ()).throw(release.Denied("NOT_LOADED")))
    monkeypatch.setattr(release, "read_owned", lambda path, *a, **kw: Path(path).read_bytes())
    seen = []
    def fake_launch(*args):
        seen.append(args)
        return SimpleNamespace(returncode=0, stdout=str(entry))
    monkeypatch.setattr(release, "launch", fake_launch)
    with pytest.raises(release.Denied, match="WORKER_CUTOVER_FAILED_PRIOR_RESTORED"):
        release.change_worker(tmp_path, prior, tmp_path, lambda: True)
    assert plist.read_bytes() == old
    assert sum(call[0] == "bootout" for call in seen) == 2
    assert sum(call[0] == "bootstrap" for call in seen) == 2
    assert all(release.WORKER_LABEL in " ".join(call) or
               call[0] == "bootstrap" for call in seen)
    assert not any("ollama" in " ".join(call) for call in seen)

def test_exact_delta_only_accepts_one_replacement():
    before = (b"prefix\\n" + release.OLD_GATE.encode() + b"\\nsuffix\\n")
    proposed = before.replace(release.OLD_GATE.encode(), release.NEW_GATE.encode())
    release.require_exact_worker_delta(before, proposed)
    with pytest.raises(release.Denied, match="CANDIDATE_EXCEEDS_REVIEWED_WORKER_SCOPE"):
        release.require_exact_worker_delta(before, proposed + b"extra")
    with pytest.raises(release.Denied, match="PRIOR_WORKER_GATE_CHANGED"):
        release.require_exact_worker_delta(b"unrelated", proposed)

