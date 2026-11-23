"""Bounded rollout-readiness bridge: synthetic host, no service or secret reads."""
import json
from pathlib import Path

from scripts import m1_foundation_rollout_readiness as probe
from scripts.m1_development_bridge import parse_request


def test_functional_view_readback_never_exports_owner_records(monkeypatch, tmp_path):
    from types import SimpleNamespace, ModuleType
    import sys
    import json as json_module
    from ai_foundation import human_model_context as context_module
    from ai_foundation import guard as guard_module
    from ai_foundation import core as core_module
    root = tmp_path / "external" / "HumanModel"
    root.mkdir(parents=True)
    installed = tmp_path / "installed"
    installed.mkdir()
    (installed / "human-model-bindings.json").write_text(
        json_module.dumps({"version": 1, "bindings": [{
            "owner_id": "private-owner", "root": str(root),
            "view_id": "personal", "scopes": ["career"],
            "max_privacy": "private",
        }]}))
    monkeypatch.setattr(probe.readiness, "existing_ledger_roots", lambda: [root])
    monkeypatch.setattr(probe.readiness, "installed_paths",
                        lambda: (tmp_path / "operator.py", installed))
    monkeypatch.setattr(probe.readiness, "_owner_record",
                        lambda docker: {"count": 1, "owner": "private-owner"})
    monkeypatch.setattr(probe, "_humanmodel_view_readback", probe._humanmodel_view_readback)
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/true")
    class Reader:
        def __call__(self, root, **kwargs):
            return {"view_id": "personal", "scope": "career", "view_revision": 1,
                    "snapshot_sha256": "a" * 64, "truncated": False,
                    "next_offset": None, "omitted_record_ids": [],
                    "records": [{
                        "id": "private-source-id", "scope": "career",
                        "privacy": "private", "content": "PRIVATE-OWNER-RAW",
                    }]}
    monkeypatch.setattr(context_module, "_source_reader", lambda repo: Reader())
    row = probe._humanmodel_view_readback()
    assert row["status"] == "READ_VERIFIED"
    assert row["guarded_read"] is True
    assert row["records_observed"] == 1
    assert row["model_calls"] == 0
    assert "PRIVATE" not in json_module.dumps(row)
    monkeypatch.setattr(probe.readiness, "_owner_record",
                        lambda docker: {"count": 2, "owner": "private-owner"})
    assert probe._humanmodel_view_readback() == {
        "status": "UNAVAILABLE", "guarded_read": False,
    }


def test_functional_view_requires_structural_owner_checks(monkeypatch):
    calls = []
    monkeypatch.setattr(probe, "_humanmodel_view_readback",
                        lambda: calls.append(True) or {"status": "READ_VERIFIED"})
    monkeypatch.setattr(probe, "_humanmodel_readiness",
                        lambda: {"status": "BLOCKED", "binding_prerequisites_ready": False})
    monkeypatch.setattr(probe, "require_m1", lambda: None)
    monkeypatch.setattr(probe.readiness, "installed_paths", lambda: None)
    monkeypatch.setattr(probe, "source_status", lambda: {"files": {}})
    monkeypatch.setattr(probe, "_local9b_release_prerequisites",
                        lambda: {"status": "BLOCKED", "reason": "PREVIOUS_WORKER_UNVERIFIED"})
    observed = probe.rollout_readiness()
    assert observed["humanmodel_view_readback"] == {
        "status": "NOT_CHECKED", "guarded_read": False,
    }
    assert not calls
    assert observed["release_permitted"] is False


def test_exact_owner_issue_operation_is_fixed():
    assert parse_request(
        "Foundation M1 Bridge: rollout-readiness",
        '<!-- foundation-m1-bridge: {"version":1,"operation":"rollout-readiness"} -->',
    ) == "rollout-readiness"


def test_readiness_redacts_owner_private_data(monkeypatch, tmp_path, capsys):
    script = tmp_path / "installed" / "scripts" / "operator_server.py"
    script.parent.mkdir(parents=True)
    script.write_bytes((probe._REPO / "scripts/operator_server.py").read_bytes())
    module = script.parent.parent / "src/ai_foundation/operator_server.py"
    module.parent.mkdir(parents=True)
    module.write_bytes((probe._REPO / "src/ai_foundation/operator_server.py").read_bytes())
    monkeypatch.setattr(probe, "require_m1", lambda: None)
    monkeypatch.setattr(probe.readiness, "installed_paths", lambda: (script, tmp_path))
    def structural_only():
        print(json.dumps({
            "status": "READY_FOR_REVIEWED_BINDING",
            "binding_prerequisites_ready": True,
            "identity": {"single_server_owner": True,
                         "binding_owner_matches": True,
                         "secret_address": "PRIVATE-NEVER-PUBLISH"},
            "ledger": {"source_snapshot_verified": True,
                       "records": ["PRIVATE-NEVER-PUBLISH"]},
            "blockers": [],
        }))
        return 0
    monkeypatch.setattr(probe.readiness, "main", structural_only)
    monkeypatch.setattr(probe, "_humanmodel_view_readback",
                        lambda: {"status": "NOT_CHECKED", "guarded_read": False})
    digest = probe._owner_source_hash(probe._REPO / "scripts/local9b_autodev_worker.py")
    monkeypatch.setattr(probe, "source_status", lambda: {
        "state": "OBSERVED",
        "files": {
            "worker": {"state": "OBSERVED", "sha256": digest},
            "failure_intake": {"state": "UNAVAILABLE"},
        },
    })
    calls = []
    def prereq():
        calls.append(True)
        return {"status": "BLOCKED", "reason": "PINNED_NATIVE_E2E_MISSING"}
    monkeypatch.setattr(probe, "_local9b_release_prerequisites", prereq)
    result = probe.rollout_readiness()
    assert result["local9b_release_prerequisites"] == {
        "status": "NOT_APPLICABLE", "reason": "INSTALLED_SOURCE_CURRENT_MAIN"
    }
    assert not calls
    assert result["deployed"]["operator_launcher"] == "CURRENT_MAIN"
    assert result["deployed"]["operator_package"] == "CURRENT_MAIN"
    assert result["deployed"]["local9b_worker"] == "CURRENT_MAIN"
    assert result["deployed"]["local9b_failure_intake"] == "UNAVAILABLE"
    assert result["humanmodel"]["nonempty_view_verified"]
    assert not result["release_permitted"]
    assert result["service_mutations"] == result["native_dispatches"] == 0
    assert "PRIVATE-NEVER-PUBLISH" not in json.dumps(result)
    assert capsys.readouterr().out == ""


def test_no_installed_operator_or_approved_view_is_unverified(monkeypatch):
    monkeypatch.setattr(probe, "require_m1", lambda: None)
    monkeypatch.setattr(probe.readiness, "installed_paths", lambda: None)
    monkeypatch.setattr(probe.readiness, "main", lambda: print(json.dumps({
        "status": "BLOCKED",
        "diagnostic_complete": True,
        "blockers": ["NO_HUMANMODEL_EVIDENCE", "UNTRUSTED_SECRET"],
        "identity": {"single_server_owner": False},
    })))
    monkeypatch.setattr(probe, "source_status", lambda: {"files": {
        "worker": {"state": "UNAVAILABLE"},
        "failure_intake": {"state": "UNAVAILABLE"},
    }})
    monkeypatch.setattr(probe, "_local9b_release_prerequisites",
                        lambda: {"status": "BLOCKED", "reason": "PREVIOUS_WORKER_UNVERIFIED"})
    report = probe.rollout_readiness()
    assert report["local9b_release_prerequisites"] == {
        "status": "BLOCKED", "reason": "PREVIOUS_WORKER_UNVERIFIED"
    }
    assert report["deployed"]["operator_launcher"] == "UNAVAILABLE"
    assert report["deployed"]["operator_package"] == "UNVERIFIED"
    assert report["humanmodel"]["status"] == "BLOCKED"
    assert report["humanmodel"]["blockers"] == ["NO_HUMANMODEL_EVIDENCE"]
    assert "UNTRUSTED_SECRET" not in json.dumps(report)
    assert report["release_permitted"] is False


def test_untrusted_source_is_not_proof(monkeypatch, tmp_path):
    path = tmp_path / "source"
    path.write_text("test")
    sym = tmp_path / "symlink"
    sym.symlink_to(path)
    assert probe._owner_source_hash(sym) is None
    monkeypatch.setattr(probe.readiness, "main", lambda: print("nondiagnostic"))
    assert probe._humanmodel_readiness() == {
        "status": "UNAVAILABLE", "blockers": ["READINESS_PROBE_FAILED"]
    }


def test_incomplete_diagnostic_is_unknown_not_false(monkeypatch):
    # An early Docker/ledger failure never checked owner or approved View.
    # It must not manufacture "owner does not exist" from missing fields.
    marker = "PRIVATE-SOURCE-CONTENT"
    monkeypatch.setattr(probe.readiness, "main", lambda: print(json.dumps({
        "status": "BLOCKED", "diagnostic_complete": False,
        "error_type": "CalledProcessError",
        "secret_trace": marker,
    })))
    data = probe._humanmodel_readiness()
    assert data["status"] == "BLOCKED"
    assert data["diagnostic_complete"] is False
    assert data["diagnostic_error_type"] == "CalledProcessError"
    assert data["binding_prerequisites_ready"] is None
    assert data["single_server_owner"] is None
    assert data["nonempty_view_verified"] is None
    assert data["binding_owner_matches"] is None
    assert data["blockers"] == []
    assert marker not in json.dumps(data)


def test_explicit_negative_owner_is_preserved_and_unknown_error_is_redacted(monkeypatch):
    monkeypatch.setattr(probe.readiness, "main", lambda: print(json.dumps({
        "status": "BLOCKED", "diagnostic_complete": True,
        "identity": {"single_server_owner": False},
        "ledger": {"source_snapshot_verified": False},
        "binding_prerequisites_ready": False,
        "error_type": "PrivateLedgerAccessFailureWithSecret",
        "blockers": ["SERVER_OWNER_NOT_UNIQUE", "PRIVATE-NEVER-PUBLISH"],
    })))
    data = probe._humanmodel_readiness()
    assert data["single_server_owner"] is False
    assert data["nonempty_view_verified"] is False
    assert data["binding_owner_matches"] is None
    assert data["diagnostic_error_type"] == "OTHER"
    assert data["blockers"] == ["SERVER_OWNER_NOT_UNIQUE"]
    assert "PrivateLedger" not in json.dumps(data)


def test_boolean_fields_are_never_inferred_from_truthy_strings(monkeypatch):
    monkeypatch.setattr(probe.readiness, "main", lambda: print(json.dumps({
        "status": "BLOCKED", "diagnostic_complete": "yes",
        "identity": {"single_server_owner": "true"},
        "ledger": {"source_snapshot_verified": 1},
        "binding_prerequisites_ready": "ready",
    })))
    data = probe._humanmodel_readiness()
    assert data["diagnostic_complete"] is None
    assert data["single_server_owner"] is None
    assert data["nonempty_view_verified"] is None
    assert data["binding_prerequisites_ready"] is None


def test_failure_stage_distinguishes_ledger_scan_from_owner_service(monkeypatch):
    def examine(row):
        monkeypatch.setattr(probe.readiness, "main", lambda: print(json.dumps(row)))
        return probe._humanmodel_readiness()
    base = {"status": "BLOCKED", "diagnostic_complete": False,
            "error_type": "CalledProcessError", "untrusted_private_path": "PRIVATE"}
    early = examine(base)
    assert early["diagnostic_phase"] == "HOST_OR_LEDGER_DISCOVERY"
    owner = examine({**base, "ledger_candidates": 1})
    assert owner["diagnostic_phase"] == "SERVER_OWNER_LOOKUP"
    after_owner = examine({**base, "ledger_candidates": 1,
                           "identity": {"single_server_owner": True}})
    assert after_owner["diagnostic_phase"] == "BINDING_LEDGER_OR_RUNTIME"
    after_runtime = examine({**base, "runtime": {}})
    assert after_runtime["diagnostic_phase"] == "FINAL_STATUS"
    assert "PRIVATE" not in json.dumps([early, owner, after_owner, after_runtime])
    assert all(r["diagnostic_error_type"] == "CalledProcessError"
               for r in [early, owner, after_owner, after_runtime])
    assert all(r["binding_prerequisites_ready"] is None
               for r in [early, owner, after_owner, after_runtime])



def test_owner_service_state_cannot_export_untrusted_values(monkeypatch):
    for raw,expected in (
        ("CONTAINER_STOPPED","CONTAINER_STOPPED"),
        ("CONTAINER_RUNNING_QUERY_FAILED","CONTAINER_RUNNING_QUERY_FAILED"),
        ("PRIVATE_ACCOUNT_OR_PASSWORD",None),
        ({"password":"private"},None),
    ):
        monkeypatch.setattr(probe.readiness,"main",
                            lambda row=raw: print(json.dumps({
                                "status":"BLOCKED", "diagnostic_complete":False,
                                "ledger_candidates":1,
                                "owner_service_state":row,
                                "error_type":"CalledProcessError",
                            })))
        row=probe._humanmodel_readiness()
        assert row["owner_service_state"]==expected
        assert row["diagnostic_phase"]=="SERVER_OWNER_LOOKUP"
        assert "PRIVATE" not in json.dumps(row)


def test_local9b_readonly_preflight_returns_category_not_private_filename():
    secret = "/Volumes/PRIVATE-SECRET/path/native_fake_e2e.py"
    def missing(_home):
        raise FileNotFoundError(2, "No such file", secret)
    result = probe._local9b_release_prerequisites(missing)
    assert result == {"status": "BLOCKED", "reason": "PINNED_NATIVE_E2E_MISSING"}
    assert "PRIVATE-SECRET" not in json.dumps(result)
    assert probe._local9b_release_prerequisites(lambda _home: ("ok",)) == {
        "status": "PREREQUISITES_OBSERVED", "reason": None,
    }


def test_local9b_readonly_preflight_is_fail_closed_on_unknown_missing_path():
    def missing(_home):
        raise FileNotFoundError(2, "Not Found", "/owner-private/unexpected-key")
    result = probe._local9b_release_prerequisites(missing)
    assert result == {"status": "BLOCKED", "reason": "REQUIRED_RELEASE_FILE_MISSING"}
    assert "owner-private" not in json.dumps(result)



def test_toolhive_owner_diagnostic_never_exports_private_data(tmp_path):
    import json
    from hashlib import sha256
    from ai_foundation.toolhive_owner_runtime import (
        TOOLHIVE_OWNER_DIR, TOOLHIVE_ARCHIVE_SHA256)
    directory = tmp_path / TOOLHIVE_OWNER_DIR
    assert probe._toolhive_owner_readback(tmp_path) == {
        "status": "INSTALL_DIRECTORY_ABSENT"}
    directory.mkdir(parents=True)
    directory.chmod(0o700)
    assert probe._toolhive_owner_readback(tmp_path) == {
        "status": "EXECUTABLE_ABSENT"}
    binary = directory / "thv"
    binary.write_bytes(b"SYNTHETIC_CLI_SECRET_CONTENT")
    binary.chmod(0o700)
    assert probe._toolhive_owner_readback(tmp_path) == {
        "status": "PINNED_RECEIPT_MISSING"}
    (directory / "archive.sha256").write_text(TOOLHIVE_ARCHIVE_SHA256 + "\n")
    (directory / "executable.sha256").write_text(
        sha256(binary.read_bytes()).hexdigest() + "\n")
    assert probe._toolhive_owner_readback(tmp_path) == {
        "status": "PINNED_PROVENANCE_VERIFIED"}
    binary.write_bytes(b"ALTERED_SECRET_CONTENT")
    observed = probe._toolhive_owner_readback(tmp_path)
    assert observed == {"status": "PINNED_PROVENANCE_MISMATCH"}
    assert "SECRET" not in json.dumps(observed)
    directory.chmod(0o777)
    assert probe._toolhive_owner_readback(tmp_path) == {
        "status": "OWNER_DIRECTORY_UNTRUSTED"}


def test_toolhive_files_runtime_readback_is_fixed_and_no_secret_egress(monkeypatch):
    import subprocess
    from types import SimpleNamespace
    from ai_foundation import toolhive_owner_runtime
    monkeypatch.setattr(toolhive_owner_runtime,"owner_toolhive_binary",
                        lambda: Path("/synthetic-owner/thv"))
    seen=[]
    def cli(argv,**kwargs):
        seen.append((argv,kwargs))
        return SimpleNamespace(returncode=0,stdout=json.dumps({
            "name":"ai-foundation-fs","status":"running",
            "url":"PRIVATE_OWNER_ENDPOINT"}),stderr="SECRET")
    monkeypatch.setattr(subprocess,"run",cli)
    assert probe._toolhive_files_runtime_readback()=={"status":"RUNNING"}
    assert seen[0][0]==["/synthetic-owner/thv","status","ai-foundation-fs",
                         "--format","json"]
    assert seen[0][1]["timeout"]==4
    assert "PRIVATE" not in json.dumps(probe._toolhive_files_runtime_readback())
    for state,code in (("stopped","STOPPED"),("starting","STARTING"),
                       ("unhealthy","UNHEALTHY"),("error","ERROR"),
                       ("auth_retrying","AUTH_RETRYING")):
        monkeypatch.setattr(subprocess,"run",lambda *a,s=state,**kw:
                            SimpleNamespace(returncode=0,stdout=json.dumps({
                                "name":"ai-foundation-fs","status":s}),stderr="SECRET"))
        assert probe._toolhive_files_runtime_readback()=={"status":code}
    monkeypatch.setattr(subprocess,"run",lambda *a,**kw:
                        SimpleNamespace(returncode=0,stdout=json.dumps({
                            "name":"OTHER","status":"running"}),stderr="SECRET"))
    assert probe._toolhive_files_runtime_readback()=={"status":"STATUS_INVALID"}
    monkeypatch.setattr(subprocess,"run",lambda *a,**kw:
                        SimpleNamespace(returncode=1,stdout="PRIVATE",stderr="SECRET"))
    assert probe._toolhive_files_runtime_readback()=={"status":"STATUS_NOT_OK"}
    monkeypatch.setattr(toolhive_owner_runtime,"owner_toolhive_binary",lambda: None)
    assert probe._toolhive_files_runtime_readback()=={"status":"CLI_UNVERIFIED"}


def test_code_workspace_and_repo_workload_are_readonly_and_redacted(tmp_path, monkeypatch):
    import plistlib
    import subprocess
    from types import SimpleNamespace
    from ai_foundation import toolhive_owner_runtime
    plist = tmp_path / "Library/LaunchAgents/dev.quest7070.ai-foundation.operator.plist"
    plist.parent.mkdir(parents=True)
    def save(env):
        plist.write_bytes(plistlib.dumps({
            "Label": "dev.quest7070.ai-foundation.operator",
            "EnvironmentVariables": env,
        }))
        plist.chmod(0o600)
    save({})
    assert probe._code_workspace_binding_readback(tmp_path) == "EXPLICIT_WORKSPACE_UNBOUND"
    workspace = tmp_path / "owner-repo"
    workspace.mkdir()
    workspace.chmod(0o700)
    save({"AI_FOUNDATION_REPO_ROOT": str(workspace)})
    assert probe._code_workspace_binding_readback(tmp_path) == "EXPLICIT_WORKSPACE_PRESENT"
    monkeypatch.setattr(toolhive_owner_runtime, "owner_toolhive_binary",
                        lambda: Path("/synthetic-owner/thv"))
    calls=[]
    def fake(argv, **opts):
        calls.append(argv)
        return SimpleNamespace(returncode=0,
            stdout=json.dumps({"name":"ai-foundation-repo",
                               "status":"running","owner_secret":"PRIVATE_SOURCE"}),
            stderr="PRIVATE")
    monkeypatch.setattr(subprocess,"run",fake)
    assert probe._toolhive_files_runtime_readback("ai-foundation-repo") == {"status":"RUNNING"}
    assert calls == [["/synthetic-owner/thv","status","ai-foundation-repo",
                      "--format","json"]]
    assert probe._toolhive_files_runtime_readback("arbitrary-unsafe-server") == {
        "status": "STATUS_INVALID"}
    assert "PRIVATE" not in json.dumps({
        "runtime": probe._toolhive_files_runtime_readback("ai-foundation-repo"),
        "binding": probe._code_workspace_binding_readback(tmp_path)})


def test_existing_code_candidate_requires_owner_git_identity_and_exports_only_state(tmp_path,monkeypatch):
    import subprocess
    from types import SimpleNamespace
    assert probe._existing_code_workspace_candidate(tmp_path) == "CANDIDATE_ABSENT"
    repo=tmp_path/"Develop"/"AI-Foundation"
    repo.mkdir(parents=True)
    repo.chmod(0o700)
    calls=[]
    def fake(argv,**opts):
        calls.append(argv)
        if "rev-parse" in argv:
            return SimpleNamespace(returncode=0,stdout=str(repo.resolve())+"\n")
        return SimpleNamespace(returncode=0,
            stdout="git@github.com:quest7070-dev/AI-Foundation.git\n")
    monkeypatch.setattr(subprocess,"run",fake)
    assert probe._existing_code_workspace_candidate(tmp_path) == "EXISTING_OWNER_CHECKOUT_VERIFIED"
    assert len(calls)==2 and calls[1][-3:] == ["config","--get","remote.origin.url"]
    def mismatched(argv,**opts):
        if "rev-parse" in argv:
            return SimpleNamespace(returncode=0,stdout=str(repo.resolve())+"\n")
        return SimpleNamespace(returncode=0,stdout="https://PRIVATE-TOKEN@other.example/repo")
    monkeypatch.setattr(subprocess,"run",mismatched)
    result=probe._existing_code_workspace_candidate(tmp_path)
    assert result=="CANDIDATE_REPOSITORY_IDENTITY_UNVERIFIED"
    assert "PRIVATE" not in result
    def alias_only(argv, **opts):
        if "rev-parse" in argv:
            return SimpleNamespace(returncode=0, stdout=str(repo.resolve())+"\n")
        if argv[-1] == "remote.github-dev.url":
            return SimpleNamespace(returncode=0,
                stdout="github-dev:quest7070-dev/AI-Foundation.git\n")
        return SimpleNamespace(returncode=1, stdout="")
    monkeypatch.setattr(subprocess, "run", alias_only)
    assert probe._existing_code_workspace_candidate(tmp_path) == "EXISTING_OWNER_CHECKOUT_VERIFIED"
    def exact_source(argv, **opts):
        if argv[-2:] == ["rev-parse", "--show-toplevel"]:
            return SimpleNamespace(returncode=0, stdout=str(repo.resolve())+"\n")
        if argv[-2:] == ["rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="a"*40+"\n")
        if argv[-1] == "--untracked-files=normal":
            return SimpleNamespace(returncode=0, stdout="")
        return SimpleNamespace(returncode=1, stdout="")
    monkeypatch.setattr(subprocess, "run", exact_source)
    assert (probe._existing_code_workspace_candidate(tmp_path)
            == "EXISTING_OWNER_CHECKOUT_VERIFIED_BY_COMMIT")
