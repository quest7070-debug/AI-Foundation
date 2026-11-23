"""Fixed Operator launchd definition: no real service launch in tests."""
import plistlib
from pathlib import Path
import pytest
from scripts.m1_operator_release_host import candidate_operator_plist,OperatorHostDenied,LABEL


def test_candidate_replaces_only_fixed_operator_and_preserves_config(tmp_path):
    prior="/private/owner/releases/old/scripts/owner_operator.py"
    stage=tmp_path/"staged"
    source=stage/"scripts/operator_server.py"
    source.parent.mkdir(parents=True)
    source.write_text("fixed reviewed operator")
    old=plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": ["/opt/homebrew/bin/python3.12","-B",prior,
                             "--config","/private/owner/config.json","--port","8766"],
        "KeepAlive":True,"WorkingDirectory":"/private/owner/releases/old",
        "EnvironmentVariables":{"MY_KEEP":"stable","PYTHONPATH":"/old/src"}})
    next_bytes, script=candidate_operator_plist(old,Path(prior),stage)
    row=plistlib.loads(next_bytes)
    assert script==str(source)
    assert row["ProgramArguments"]==[
        "/opt/homebrew/bin/python3.12","-B",str(source),"--config",
        "/private/owner/config.json","--port","8766"]
    assert row["KeepAlive"] is True
    assert row["EnvironmentVariables"]["MY_KEEP"]=="stable"
    assert "/old/src" not in row["EnvironmentVariables"]["PYTHONPATH"]
    assert row["WorkingDirectory"]==str(stage)


@pytest.mark.parametrize("arguments",[
    ["/bin/bash","/prior/scripts/owner_operator.py","--config","/private/config.json"],
    ["/usr/bin/python3","-c","/prior/scripts/owner_operator.py","--config","/private/config.json"],
    ["/usr/bin/python3","/prior/scripts/owner_operator.py","--config","/private/config.json","--port","8768"],
    ["/usr/bin/python3","/prior/scripts/owner_operator.py","--config","../config.json"],
    ["/usr/bin/python3","/prior/scripts/owner_operator.py","--config","/private/config.json","--unknown","YES"],
])
def test_rejects_unreviewed_launcher_or_port(tmp_path,arguments):
    stage=tmp_path/"candidate"
    path=stage/"scripts/operator_server.py"
    path.parent.mkdir(parents=True)
    path.write_text("fixed")
    plist=plistlib.dumps({"Label":LABEL,"ProgramArguments":arguments})
    with pytest.raises(OperatorHostDenied):
        candidate_operator_plist(plist,Path("/prior/scripts/owner_operator.py"),stage)


def test_candidate_cannot_be_untrusted_or_symlinked(tmp_path):
    stage=tmp_path/"candidate"
    stage.mkdir()
    script=stage/"scripts/operator_server.py"
    script.parent.mkdir()
    other=tmp_path/"other.py"
    other.write_text("untrusted")
    script.symlink_to(other)
    plist=plistlib.dumps({
        "Label":LABEL,
        "ProgramArguments":["/usr/bin/python3","/prior/scripts/owner_operator.py",
                            "--config","/private/config.json"]})
    with pytest.raises(OperatorHostDenied,match="ENTRY_MISSING"):
        candidate_operator_plist(plist,Path("/prior/scripts/owner_operator.py"),stage)



def test_atomic_operator_plist_retains_exact_private_mode(tmp_path):
    import os
    import stat
    from scripts.m1_operator_release_host import FixedOperatorHost
    plist=tmp_path/"dev.quest7070.ai-foundation.operator.plist"
    plist.write_bytes(b"old")
    plist.chmod(0o600)
    host=object.__new__(FixedOperatorHost)
    host.plist=plist
    host._atomic_plist(b"new")
    assert plist.read_bytes()==b"new"
    assert stat.S_IMODE(plist.stat().st_mode)==0o600
    plist.chmod(0o666)
    with pytest.raises(OperatorHostDenied,match="OWNER_CHANGED"):
        host._atomic_plist(b"refused")



def test_corrupt_new_candidate_does_not_block_old_rollback_material(tmp_path):
    import json
    from ai_foundation.release_gate import ImmutableReleaseScope
    from scripts.m1_operator_release_host import FixedOperatorHost
    scope=ImmutableReleaseScope(
        path="m1-operator",source_sha="a"*64,
        previous_authority="old",previous_endpoint="old",
        candidate_authority="new",candidate_endpoint="new",
        rollback_procedure="restore",switch_target="operator",
        readback_target="newpid",rollback_readback_target="oldpid")
    stage=tmp_path/"Library/Application Support/AI-Foundation/operator-release-staging"/scope.scope_ref
    stage.mkdir(parents=True,mode=0o700)
    original=b"safe old plist bytes"
    entry=b"safe old source bytes"
    import hashlib
    hashbytes=lambda b:hashlib.sha256(b).hexdigest()
    (stage/"previous-launchagent.plist").write_bytes(original)
    (stage/"previous-operator-entry.py").write_bytes(entry)
    (stage/"manifest.json").write_text(json.dumps({
        "schema":1,"scope_ref":scope.scope_ref,
        "prior_plist_sha256":hashbytes(original),
        "prior_entry_sha256":hashbytes(entry),
        "tracked":{"scripts/operator_server.py":"a"*64},
        "prior_entry_path":str(tmp_path/"old.py")}))
    for name in ("previous-launchagent.plist","previous-operator-entry.py","manifest.json"):
        (stage/name).chmod(0o600)
    host=object.__new__(FixedOperatorHost)
    host.home=tmp_path
    host.stage=stage
    host.expected_scope=scope.scope_ref
    # The new candidate is entirely missing/corrupt; old rollback still reads.
    manifest,backed=host._rollback_material(scope)
    assert backed==original and manifest["prior_entry_sha256"]==hashbytes(entry)
    with pytest.raises((OSError, ValueError, RuntimeError)):
        host._manifest(scope)



def test_live_readback_rejects_missing_stage_before_any_http_calls(tmp_path):
    from ai_foundation.release_gate import ImmutableReleaseScope
    from scripts.m1_operator_release_host import FixedOperatorHost
    scope=ImmutableReleaseScope(
        path="m1-operator",source_sha="b"*64,
        previous_authority="old",previous_endpoint="old",
        candidate_authority="github-commit:"+"a"*40,candidate_endpoint="new",
        rollback_procedure="restore",switch_target="operator",
        readback_target="pid",rollback_readback_target="oldpid")
    host=object.__new__(FixedOperatorHost)
    host.home=tmp_path
    host.plist=tmp_path/"operator.plist"
    host.plist.write_bytes(b"new")
    host.candidate_definition=b"new"
    host.stage=tmp_path/"missing"
    host.expected_scope=scope.scope_ref
    host._pid_owned=lambda: (_ for _ in ()).throw(AssertionError("No HTTP/PID allowed"))
    assert host.readback_operator(scope) is False


def test_launchd_settle_wait_requires_two_consecutive_absent_observations(monkeypatch):
    from scripts import m1_operator_release_host as mod
    from scripts.m1_operator_release_host import FixedOperatorHost
    host = object.__new__(FixedOperatorHost)
    observations = iter([True, False, True, False, False])
    host._registered = lambda: next(observations)
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)
    assert host._await_unregistered() is True


def test_launchd_settle_timeout_is_bounded_without_bootstrap(monkeypatch):
    from scripts import m1_operator_release_host as mod
    from scripts.m1_operator_release_host import FixedOperatorHost
    host = object.__new__(FixedOperatorHost)
    seen = []
    host._registered = lambda: seen.append("print") or True
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)
    assert host._await_unregistered() is False
    assert len(seen) == 60


def test_launchd_bootstrap_retries_only_known_transient_error_when_label_absent(
        monkeypatch, tmp_path):
    from types import SimpleNamespace
    from scripts import m1_operator_release_host as mod
    from scripts.m1_operator_release_host import FixedOperatorHost
    host = object.__new__(FixedOperatorHost)
    host.plist = tmp_path/"operator.plist"
    seen = []
    results = iter([
        SimpleNamespace(returncode=5,
                        stderr="Bootstrap failed: 5: Input/output error"),
        SimpleNamespace(returncode=0, stderr=""),
    ])
    host._launch = lambda *a: seen.append(a) or next(results)
    host._registered = lambda: False
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)
    host._bootstrap_settled()
    assert len(seen) == 2
    assert all(x[0] == "bootstrap" for x in seen)


def test_launchd_bootstrap_does_not_retry_permanent_error(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from scripts.m1_operator_release_host import FixedOperatorHost
    host = object.__new__(FixedOperatorHost)
    host.plist = tmp_path/"operator.plist"
    seen = []
    host._launch = lambda *a: seen.append(a) or SimpleNamespace(
        returncode=1, stderr="Bootstrap failed: permission denied")
    host._registered = lambda: (_ for _ in ()).throw(
        AssertionError("unknown error must not probe or retry"))
    with pytest.raises(OperatorHostDenied, match="OPERATOR_BOOTSTRAP_REJECTED"):
        host._bootstrap_settled()
    assert len(seen) == 1


def test_launchd_bootstrap_never_retries_if_label_was_registered(
        monkeypatch, tmp_path):
    from types import SimpleNamespace
    from scripts.m1_operator_release_host import FixedOperatorHost
    host = object.__new__(FixedOperatorHost)
    host.plist = tmp_path/"operator.plist"
    seen = []
    host._launch = lambda *a: seen.append(a) or SimpleNamespace(
        returncode=5, stderr="Bootstrap failed: 5: Input/output error")
    host._registered = lambda: True
    with pytest.raises(OperatorHostDenied, match="OPERATOR_BOOTSTRAP_REJECTED_LABEL_PRESENT"):
        host._bootstrap_settled()
    assert len(seen) == 1


def test_bootstrap_transient_retries_are_bounded(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from scripts import m1_operator_release_host as mod
    from scripts.m1_operator_release_host import FixedOperatorHost
    host = object.__new__(FixedOperatorHost)
    host.plist = tmp_path/"operator.plist"
    seen = []
    host._launch = lambda *a: seen.append(a) or SimpleNamespace(
        returncode=5, stderr="Bootstrap failed: 5: Input/output error")
    host._registered = lambda: False
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)
    with pytest.raises(OperatorHostDenied, match="OPERATOR_BOOTSTRAP_REJECTED_RETRY_EXHAUSTED"):
        host._bootstrap_settled()
    assert len(seen) == 10


def test_switch_waits_for_deregistration_before_writing_candidate(tmp_path):
    from types import SimpleNamespace
    from scripts.m1_operator_release_host import FixedOperatorHost
    host = object.__new__(FixedOperatorHost)
    host.target = "gui/501/dev.quest7070.ai-foundation.operator"
    host.candidate_definition = b"reviewed"
    scope = SimpleNamespace(scope_ref="s" * 64)
    seen = []
    host.verify_candidate = lambda _: True
    host.current_scope_ref = lambda: scope.scope_ref
    host._human = lambda: {"activity": []}
    host._pid_owned = lambda: True
    host._launch = lambda *args: seen.append(args[0]) or SimpleNamespace(
        returncode=0)
    host._await_unregistered = lambda: seen.append("settled") or True
    host._atomic_plist = lambda data: seen.append("candidate_write")
    host._bootstrap_settled = lambda **kw: seen.append("bootstrap")
    host.switch_operator(scope)
    assert seen == ["bootout", "settled", "candidate_write", "bootstrap"]


def test_switch_does_not_install_candidate_until_label_is_gone(tmp_path):
    from types import SimpleNamespace
    from scripts.m1_operator_release_host import FixedOperatorHost
    host = object.__new__(FixedOperatorHost)
    host.target = "gui/501/dev.quest7070.ai-foundation.operator"
    host.candidate_definition = b"reviewed"
    scope = SimpleNamespace(scope_ref="s" * 64)
    seen = []
    host.verify_candidate = lambda _: True
    host.current_scope_ref = lambda: scope.scope_ref
    host._human = lambda: {"activity": []}
    host._pid_owned = lambda: True
    host._launch = lambda *args: seen.append(args[0]) or SimpleNamespace(
        returncode=0)
    host._await_unregistered = lambda: False
    host._atomic_plist = lambda data: pytest.fail(
        "must never modify plist until label is removed")
    host._bootstrap_settled = lambda **kw: pytest.fail(
        "must never bootstrap until label is removed")
    with pytest.raises(OperatorHostDenied, match="OPERATOR_BOOTOUT_SETTLE_TIMEOUT"):
        host.switch_operator(scope)
    assert seen == ["bootout"]


def test_rollback_waits_after_teardown_before_restore_bootstrap(tmp_path):
    from types import SimpleNamespace
    from scripts.m1_operator_release_host import FixedOperatorHost
    host = object.__new__(FixedOperatorHost)
    host.plist = tmp_path/"operator.plist"
    host.plist.write_bytes(b"candidate")
    host.target = "gui/501/dev.quest7070.ai-foundation.operator"
    seen = []
    host._rollback_material = lambda _: ({}, b"old")
    host._registered = lambda: True
    host._launch = lambda *args: seen.append(args[0]) or SimpleNamespace(
        returncode=0)
    host._await_unregistered = lambda: seen.append("settled") or True
    host._atomic_plist = lambda data: seen.append("restore")
    host._bootstrap_settled = lambda **kw: seen.append(
        "rollback_bootstrap" if kw.get("rollback") else "wrong")
    host.rollback_operator(SimpleNamespace())
    assert seen == ["bootout", "settled", "restore", "rollback_bootstrap"]


def test_bootstrap_permission_denial_fails_once_with_safe_reason(tmp_path):
    from types import SimpleNamespace
    from scripts.m1_operator_release_host import FixedOperatorHost
    host = object.__new__(FixedOperatorHost)
    host.plist = tmp_path/"operator.plist"
    calls = []
    host._launch = lambda *a: calls.append(a) or SimpleNamespace(
        returncode=1, stderr="Bootstrap failed: Operation not permitted")
    host._registered = lambda: (_ for _ in ()).throw(
        AssertionError("permanent error must not inspect/retry"))
    with pytest.raises(OperatorHostDenied,
                       match="OPERATOR_BOOTSTRAP_REJECTED_PERMISSION"):
        host._bootstrap_settled()
    assert len(calls) == 1


def test_rollback_retry_reason_is_distinct_from_apply(tmp_path):
    from types import SimpleNamespace
    from scripts.m1_operator_release_host import FixedOperatorHost
    host = object.__new__(FixedOperatorHost)
    host.plist = tmp_path/"operator.plist"
    host._launch = lambda *a: SimpleNamespace(
        returncode=5, stderr="Bootstrap failed: 5: Input/output error")
    host._registered = lambda: True
    with pytest.raises(OperatorHostDenied,
                       match="ROLLBACK_BOOTSTRAP_REJECTED_LABEL_PRESENT"):
        host._bootstrap_settled(rollback=True)


def test_operator_candidate_binds_exact_reviewed_code_and_rejects_changed_alias(tmp_path):
    prior="/private/owner/release/scripts/old_operator.py"
    stage=tmp_path/"stage"
    code=tmp_path/"Develop/AI-Foundation-CODE"
    code.mkdir(parents=True)
    (stage/"scripts").mkdir(parents=True)
    (stage/"scripts/operator_server.py").write_text("synthetic")
    source={"Label":LABEL,"ProgramArguments":["/usr/bin/python3","-B",prior,
              "--config","/private/owner/config.json"]}
    candidate, _=candidate_operator_plist(
        plistlib.dumps(source),Path(prior),stage,code_workspace=code)
    row=plistlib.loads(candidate)
    env=row["EnvironmentVariables"]
    assert env["AI_FOUNDATION_REPO_ROOT"]==str(code)
    assert env["AI_FOUNDATION_TOOLHIVE_REPO_SERVER"]=="ai-foundation-repo"
    assert row["WorkingDirectory"]==str(stage)
    changed=dict(source,EnvironmentVariables={"AI_FOUNDATION_REPO_ROOT":str(tmp_path)})
    with pytest.raises(OperatorHostDenied,match="CODE_OPERATOR_BINDING_CHANGED"):
        candidate_operator_plist(plistlib.dumps(changed),Path(prior),stage,
                                 code_workspace=code)


def test_owner_code_binding_requires_pinned_clean_workspace_and_live_mcp(
        tmp_path,monkeypatch):
    import os
    from scripts import m1_operator_release_host as mod
    from scripts import m1_owner_toolhive_code_repair as recovery
    from scripts import m1_owner_toolhive_files_repair as files
    from ai_foundation import toolhive_owner_runtime
    assert mod._verified_owner_code_workspace(tmp_path) is None
    path=tmp_path/"Develop/AI-Foundation-CODE"
    gitdir=path/".git"
    gitdir.mkdir(parents=True)
    path.chmod(0o700)
    docker=tmp_path/"docker";docker.write_bytes(b"synthetic")
    thv=tmp_path/"thv";thv.write_bytes(b"synthetic")
    monkeypatch.setattr(files,"DOCKER_BINARIES",(str(docker),))
    monkeypatch.setattr(files,"pinned_container_image",lambda name: None)
    monkeypatch.setattr(toolhive_owner_runtime,"owner_toolhive_binary",lambda home: thv)
    def fake_git(root,*args):
        if args==("rev-parse","--git-common-dir"): return ".git"
        if args==("rev-parse","--show-toplevel"): return str(path.resolve())
        if args==("rev-parse","HEAD"): return mod.REVIEWED_CODE_HEAD
        return ""
    monkeypatch.setattr(recovery,"git",fake_git)
    monkeypatch.setattr(recovery.FixedCodeWorkload,"observe",
                        lambda self,plan:"RUNNING_VERIFIED_MOUNT")
    assert mod._verified_owner_code_workspace(tmp_path)==path
    monkeypatch.setattr(recovery,"git",
                        lambda root,*args:"DIRTY" if args==("status","--porcelain")
                        else fake_git(root,*args))
    with pytest.raises(OperatorHostDenied,match="CODE_WORKSPACE_IDENTITY_UNVERIFIED"):
        mod._verified_owner_code_workspace(tmp_path)


def test_live_operator_code_readback_rejects_unready_service(tmp_path,monkeypatch):
    from scripts import m1_operator_release_host as mod
    from scripts.m1_operator_release_host import FixedOperatorHost
    from types import SimpleNamespace
    host=object.__new__(FixedOperatorHost)
    host.plist=tmp_path/"operator.plist"
    candidate=plistlib.dumps({"EnvironmentVariables":{
        "AI_FOUNDATION_REPO_ROOT":str(tmp_path/"Develop/AI-Foundation-CODE")}})
    host.plist.write_bytes(candidate)
    host.candidate_definition=candidate
    host._manifest=lambda scope:{"candidate_commit":"a"*40}
    host._pid_owned=lambda:True
    state={"development":{"humanmodel_factory_registered":True},
           "services":[{"name":"TOOLHIVE CODE","ok":False}]}
    host._human=lambda:state
    monkeypatch.setattr(mod.time,"sleep",lambda seconds:None)
    scope=SimpleNamespace(candidate_authority="github-commit:"+"a"*40)
    assert host.readback_operator(scope) is False
    state["services"][0]["ok"]=True
    assert host.readback_operator(scope) is True


def test_verified_incumbent_requires_pinned_stage_and_live_command(
        tmp_path, monkeypatch):
    from types import SimpleNamespace
    from scripts import m1_operator_release_host as mod
    host = object.__new__(mod.FixedOperatorHost)
    host.home = tmp_path
    host.plist = tmp_path / "operator.plist"
    host.target = "gui/501/" + mod.LABEL
    old_ref = "c"*64
    previous_sha = "b"*40
    stage = (tmp_path / "Library/Application Support/AI-Foundation"
             / "operator-release-staging" / old_ref)
    stage.mkdir(parents=True, mode=0o700)
    entry = stage / "candidate/scripts/operator_server.py"
    source = b"print('owner-verified-source')\\n"
    entry.parent.mkdir(parents=True)
    entry.write_bytes(source)
    previous_entry = tmp_path / "prior-entry.py"
    previous_bytes = b"print('prior')\\n"
    import hashlib
    digest = hashlib.sha256(source).hexdigest()
    manifest = {"schema": 1, "scope_ref": old_ref,
                "candidate_commit": previous_sha,
                "tracked": {"scripts/operator_server.py": digest}}
    from json import dumps
    original = plistlib.dumps({"Label": mod.LABEL,
                              "ProgramArguments": ["/opt/homebrew/bin/python3.12",
                                  "-B", str(previous_entry), "--config",
                                  "/private/owner/config.json"]})
    manifest["prior_entry_path"] = str(previous_entry)
    plist, _ = mod.candidate_operator_plist(original, previous_entry,
                                           stage / "candidate")
    expected_args = plistlib.loads(plist)["ProgramArguments"]
    expected_definition = plistlib.loads(plist)
    def owned(path, *a, **kw):
        if str(path) == str(entry): return source
        if str(path) == str(host.plist): return plist
        if str(path) == str(previous_entry): return previous_bytes
        raise AssertionError("UNKNOWN_OWNER_FILE")
    monkeypatch.setattr(mod, "verify_staged", lambda p, ref: (
        str(p) == str(stage) and ref == old_ref))
    monkeypatch.setattr(mod, "_read_private", lambda p: (
        original if p.name == "previous-launchagent.plist" else dumps(manifest).encode()))
    monkeypatch.setattr(mod, "_verified_owner_code_workspace", lambda _: None)
    monkeypatch.setattr(mod, "_owned_regular_bytes", owned)
    ready = {"cmd": True, "pid": True}
    host._launch = lambda *args: SimpleNamespace(
        returncode=0,
        stdout=("program = " + expected_args[0] + "\narguments = {\n" +
                "\n".join(expected_args) + "\n}\nworking directory = " +
                expected_definition["WorkingDirectory"] + "\nenvironment = {\n" +
                "\n".join(k + " => " + v for k, v in
                          expected_definition["EnvironmentVariables"].items()) +
                "\n}\n" if ready["cmd"] else
                "diagnostic path = " + str(entry)))
    host._pid_owned = lambda: ready["pid"]
    host._human = lambda: {"development": {"humanmodel_factory_registered": True}}
    prior = SimpleNamespace(status="VERIFIED", release_scope_ref=old_ref,
                            candidate_authority="github-commit:" + previous_sha)
    assert host.verified_current_release(prior) is True
    valid_plist = plist
    changed = plistlib.loads(plist)
    changed["EnvironmentVariables"]["PYTHONPATH"] = "/unreviewed"
    plist = plistlib.dumps(changed)
    assert host.diagnose_current_release(prior) == "RUNNING_PLIST_NOT_PREDECESSOR"
    plist = valid_plist
    ready["cmd"] = False
    assert host.verified_current_release(prior) is False
    ready["cmd"] = True
    ready["pid"] = False
    assert host.verified_current_release(prior) is False
    ready["pid"] = True
    prior.candidate_authority = "github-commit:"+"d"*40
    assert host.verified_current_release(prior) is False
    prior.candidate_authority = "github-commit:"+previous_sha
    manifest["tracked"]["scripts/operator_server.py"] = "0"*64
    assert host.verified_current_release(prior) is False
    # Registry remained VERIFIED but the owner reinstated the *original*
    # backup. Do not claim the candidate is loaded or reauthorize release.
    manifest["tracked"]["scripts/operator_server.py"] = digest
    plist = plistlib.dumps({"Label": mod.LABEL,
                            "ProgramArguments": ["/opt/homebrew/bin/python3.12",
                                                 "-B", str(previous_entry)]})
    manifest["prior_plist_sha256"] = hashlib.sha256(plist).hexdigest()
    manifest["prior_entry_path"] = str(previous_entry)
    manifest["prior_entry_sha256"] = hashlib.sha256(previous_bytes).hexdigest()
    assert host.diagnose_current_release(prior) == (
        "INSTALLED_PREVIOUS_OPERATOR_RESTORED")
    assert host.verified_current_release(prior) is False


def test_incumbent_diagnosis_missing_private_stage_is_fixed_and_no_effect(tmp_path):
    from types import SimpleNamespace
    from scripts import m1_operator_release_host as mod
    host = object.__new__(mod.FixedOperatorHost)
    host.home = tmp_path
    prior = SimpleNamespace(status="VERIFIED", release_scope_ref="c"*64,
                            candidate_authority="github-commit:" + "b"*40)
    assert host.diagnose_current_release(prior) == "PREDECESSOR_STAGE_NOT_FOUND"
    assert host.verified_current_release(prior) is False
    assert not list(tmp_path.iterdir())

