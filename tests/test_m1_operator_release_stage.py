"""Operator release backup/stage is isolated, exact-scope and non-effectful."""
import json
from pathlib import Path
import plistlib
import subprocess

import pytest
from ai_foundation.release_gate import ImmutableReleaseScope
from scripts import m1_operator_release_stage as s


def preparation(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    for name in ("scripts/operator_server.py",
                 "src/ai_foundation/operator_server.py"):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("reviewed source " + name)
    home = tmp_path / "owner"
    plist = home / "Library/LaunchAgents/dev.quest7070.ai-foundation.operator.plist"
    plist.parent.mkdir(parents=True)
    old = home / "previous/scripts/operator-server-old.py"
    old.parent.mkdir(parents=True)
    old.write_text("prior source unchanged")
    plist.write_bytes(plistlib.dumps({"Label":"dev.quest7070.ai-foundation.operator",
                                     "ProgramArguments":["/usr/bin/python3",str(old)]}))
    scope = ImmutableReleaseScope(
        path="m1-operator", source_sha="1"*64,
        previous_authority="old", previous_endpoint="old",
        candidate_authority="candidate", candidate_endpoint="new",
        rollback_procedure="restore old", switch_target="operator-only",
        readback_target="pid-bound", rollback_readback_target="old-pid-bound")
    monkeypatch.setattr(s, "require_m1", lambda:None)
    monkeypatch.setattr(s, "operator_only_release_scope",
                        lambda **kw:(scope, {"status":"OBSERVED","candidate_sha":"2"*40}))
    def git(cmd, **kw):
        assert cmd[:3] == ["/usr/bin/git","-C",str(root)]
        assert cmd[-2:] == ["ls-files","-z"]
        return subprocess.CompletedProcess(cmd,0,
            b"scripts/operator_server.py\0src/ai_foundation/operator_server.py\0",b"")
    return root,home,scope,git,plist,old


def test_stages_immutable_backup_without_host_effect(tmp_path, monkeypatch):
    root,home,scope,git,plist,old = preparation(tmp_path, monkeypatch)
    old_plist=plist.read_bytes()
    result=s.stage_operator_only(root,home,git_run=git)
    assert result["status"]=="STAGED_NO_DEPLOY" and result["backup_verified"]
    assert result["service_mutations"]==result["guard_writes"]==result["native_dispatches"]==0
    assert plist.read_bytes()==old_plist and old.read_text()=="prior source unchanged"
    target=home/"Library/Application Support/AI-Foundation/operator-release-staging"/scope.scope_ref
    assert s.verify_staged(target,scope.scope_ref)
    assert (target/"previous-launchagent.plist").read_bytes()==old_plist
    assert len(json.loads((target/"manifest.json").read_text())["tracked"])==2
    assert str(home) not in json.dumps(result)
    with pytest.raises(s.StagingDenied,match="ALREADY_EXISTS"):
        s.stage_operator_only(root,home,git_run=git)


def test_backup_tamper_is_detected(tmp_path, monkeypatch):
    root,home,scope,git,_,_=preparation(tmp_path,monkeypatch)
    s.stage_operator_only(root,home,git_run=git)
    target=home/"Library/Application Support/AI-Foundation/operator-release-staging"/scope.scope_ref
    (target/"previous-operator-entry.py").write_text("different")
    with pytest.raises(s.StagingDenied,match="BACKUP_MISMATCH"):
        s.verify_staged(target,scope.scope_ref)


def test_symlinked_candidate_denied_without_writing_backup(tmp_path, monkeypatch):
    root,home,scope,git,_,_=preparation(tmp_path,monkeypatch)
    f=root/"scripts/operator_server.py"
    f.unlink()
    f.symlink_to(root/"src/ai_foundation/operator_server.py")
    with pytest.raises((ValueError, s.StagingDenied)):
        s.stage_operator_only(root,home,git_run=git)
    assert not (home/"Library/Application Support/AI-Foundation/operator-release-staging"/scope.scope_ref).exists()


def test_changed_candidate_scope_denied_and_staged_files_removed(tmp_path, monkeypatch):
    root,home,scope,git,_,_=preparation(tmp_path,monkeypatch)
    second=ImmutableReleaseScope(**{**scope.as_dict(),"source_sha":"3"*64})
    calls=[(scope,{"status":"OBSERVED","candidate_sha":"2"*40}),
           (second,{"status":"OBSERVED","candidate_sha":"2"*40})]
    monkeypatch.setattr(s, "operator_only_release_scope", lambda **kw:calls.pop(0))
    with pytest.raises(s.StagingDenied, match="SCOPE_CHANGED"):
        s.stage_operator_only(root,home,git_run=git)
    assert not (home/"Library/Application Support/AI-Foundation/operator-release-staging"/scope.scope_ref).exists()



def test_empty_regular_tracked_file_is_valid(tmp_path, monkeypatch):
    root,home,scope,git,_,_=preparation(tmp_path,monkeypatch)
    empty=root/"docs/empty.txt"
    empty.parent.mkdir(parents=True,exist_ok=True)
    empty.write_bytes(b"")
    def listfiles(cmd, **kw):
        return subprocess.CompletedProcess(cmd,0,
            b"scripts/operator_server.py\0src/ai_foundation/operator_server.py\0docs/empty.txt\0",b"")
    result=s.stage_operator_only(root,home,git_run=listfiles)
    assert result["tracked_files"]==3
    target=home/"Library/Application Support/AI-Foundation/operator-release-staging"/scope.scope_ref
    assert s.verify_staged(target,scope.scope_ref)
