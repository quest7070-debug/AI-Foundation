"""P4 no-effect release inventory synthetic host acceptance."""
import json
from pathlib import Path
import plistlib
import subprocess

import pytest

from scripts import m1_development_bridge as bridge
from scripts import m1_p4_release_inventory as probe


SHA = "3" * 40


def prepare(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "require_m1", lambda: None)
    home = tmp_path / "home"
    root = tmp_path / "repository"
    for relative in probe.CANDIDATES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("candidate:" + relative)
    for service, label, rel in probe.LABELS:
        script = home / "staged-existing" / rel
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("existing:" + service)
        plist = home / "Library/LaunchAgents" / (label + ".plist")
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_bytes(plistlib.dumps(
            {"Label": label, "ProgramArguments": ["/usr/bin/python3", str(script)]}))
    def git(args, **kw):
        assert args[:3] == ["/usr/bin/git", "-C", str(root)]
        assert args[-2:] == ["rev-parse", "HEAD"]
        return subprocess.CompletedProcess(args, 0, SHA + "\n", "")
    return home, root, git


def test_inventory_only_hashes_fixed_services_without_activation(tmp_path, monkeypatch):
    home, root, git = prepare(tmp_path, monkeypatch)
    receipt = probe.release_inventory(home=home, root=root, git_run=git)
    assert receipt["status"] == "OBSERVED"
    assert receipt["candidate_main_sha"] == SHA
    assert len(receipt["release_scope_ref"]) == 64
    assert set(receipt["services"]) == {"operator", "local9b"}
    assert all(row["existing_source_available"] for row in receipt["services"].values())
    assert all(not row["entry_matches_candidate"] for row in receipt["services"].values())
    assert receipt["mcp_source_present"] is True
    assert receipt["external_mcp_transport_verified"] is False
    assert receipt["installed_process_source_verified"] is False
    assert receipt["human_release_gate"] == "REQUIRED_NOT_GRANTED"
    assert all(row["rollback_backup_present"] is False for row in receipt["services"].values())
    assert receipt["release_permitted"] is False
    assert receipt["service_mutations"] == receipt["native_dispatches"] == 0
    assert str(home) not in json.dumps(receipt)
    assert "existing:operator" not in json.dumps(receipt)


def test_exact_prior_version_changes_scope_and_requires_new_review(tmp_path, monkeypatch):
    home, root, git = prepare(tmp_path, monkeypatch)
    old = probe.release_inventory(home=home, root=root, git_run=git)
    script = home / "staged-existing" / "scripts/operator_server.py"
    script.write_text("different existing implementation")
    new = probe.release_inventory(home=home, root=root, git_run=git)
    assert old["release_scope_ref"] != new["release_scope_ref"]
    assert new["human_release_gate"] == "REQUIRED_NOT_GRANTED"
    assert new["release_permitted"] is False


def test_missing_or_symlinked_prior_source_refuses_release_plan(tmp_path, monkeypatch):
    home, root, git = prepare(tmp_path, monkeypatch)
    script = home / "staged-existing" / "scripts/local9b_autodev_worker.py"
    script.unlink()
    assert probe.release_inventory(home=home, root=root, git_run=git)["status"] == "BLOCKED"
    script.symlink_to(root / "scripts/local9b_autodev_worker.py")
    result = probe.release_inventory(home=home, root=root, git_run=git)
    assert result["status"] == "BLOCKED"
    assert result["release_scope_ref"] is None
    assert result["release_permitted"] is False


def test_unknown_launch_agent_argument_shape_fails_closed(tmp_path, monkeypatch):
    home, root, git = prepare(tmp_path, monkeypatch)
    label = probe.LABELS[0][1]
    plist = home / "Library/LaunchAgents" / (label + ".plist")
    plist.write_bytes(plistlib.dumps({"Label": label, "ProgramArguments": [
        "/usr/bin/python3", "/somewhere/other.py"]}))
    result = probe.release_inventory(home=home, root=root, git_run=git)
    assert result["status"] == "BLOCKED"
    assert result["failed_stage"] == "OPERATOR_INSTALLED_SOURCE"
    assert result["release_permitted"] is False


def test_release_inventory_issue_has_no_shell_or_revision_overrides():
    good = '<!-- foundation-m1-bridge: {"version":1,"operation":"release-inventory"} -->'
    assert bridge.parse_request("Foundation M1 Bridge: release-inventory", good) == "release-inventory"
    with pytest.raises(bridge.BridgeDenied):
        bridge.parse_request(
            "Foundation M1 Bridge: release-inventory",
            '<!-- foundation-m1-bridge: {"version":1,"operation":"release-inventory","sha":"evil"} -->',
        )


def test_candidate_package_change_modifies_review_ref(tmp_path, monkeypatch):
    home, root, git = prepare(tmp_path, monkeypatch)
    prior = probe.release_inventory(home=home, root=root, git_run=git)
    assert prior["status"] == "OBSERVED"
    package = root / "src/ai_foundation/operator_server.py"
    package.write_text("different module under same fake git test fixture")
    next_one = probe.release_inventory(home=home, root=root, git_run=git)
    assert next_one["status"] == "OBSERVED"
    assert prior["release_scope_ref"] != next_one["release_scope_ref"]
    assert next_one["release_permitted"] is False



def test_binding_shape_never_exposes_owner_path(tmp_path, monkeypatch):
    home, root, git = prepare(tmp_path, monkeypatch)
    label = probe.LABELS[0][1]
    plist = home / "Library/LaunchAgents" / (label + ".plist")
    disguised = "/private/owner-id/private-build/python/unknown_entry.py"
    plist.write_bytes(plistlib.dumps({"Label":label,
        "ProgramArguments":["/usr/bin/python3",disguised]}))
    record = probe.release_inventory(home=home,root=root,git_run=git)
    assert record["status"] == "BLOCKED"
    assert record["failed_stage"] == "OPERATOR_INSTALLED_SOURCE"
    assert "owner-id" not in json.dumps(record) and disguised not in json.dumps(record)


def test_known_versioned_layout_remains_blocked_until_host_review(tmp_path, monkeypatch):
    home, root, git = prepare(tmp_path, monkeypatch)
    label = probe.LABELS[0][1]
    plist = home / "Library/LaunchAgents" / (label + ".plist")
    versioned = "/private/owner-id/fixed-release/operator_server.py"
    plist.write_bytes(plistlib.dumps({"Label":label,
        "ProgramArguments":["/usr/bin/python3",versioned]}))
    record = probe.release_inventory(home=home,root=root,git_run=git)
    assert record["status"] == "BLOCKED"
    assert record["failed_stage"] == "OPERATOR_INSTALLED_SOURCE"
    assert versioned not in json.dumps(record)



def test_renamed_operator_entrypoint_is_verified_by_immutable_installed_hash(tmp_path, monkeypatch):
    home, root, git = prepare(tmp_path, monkeypatch)
    label = probe.LABELS[0][1]
    installed = home / "staged-existing" / "fixed-release" / "owner_operator_p4.py"
    installed.parent.mkdir(parents=True, exist_ok=True)
    installed.write_text("trusted owner entrypoint bytes")
    plist = home / "Library/LaunchAgents" / (label + ".plist")
    plist.write_bytes(plistlib.dumps({"Label": label, "ProgramArguments": [
        "/usr/bin/python3", "-B", str(installed), "--config", "/tmp/fixed-config.json"]}))
    r = probe.release_inventory(home=home, root=root, git_run=git)
    assert r["status"] == "OBSERVED"
    assert r["services"]["operator"]["installed_entry_sha256"] == probe._digest(installed.read_bytes())
    assert r["services"]["operator"]["entry_matches_candidate"] is False
    assert len(r["release_scope_ref"]) == 64
    assert r["release_permitted"] is False
    assert "owner_operator_p4.py" not in json.dumps(r)
    # A different installed source is a NEW scope, not silent permission.
    installed.write_text("changed owner entrypoint bytes")
    changed=probe.release_inventory(home=home, root=root, git_run=git)
    assert changed["release_scope_ref"] != r["release_scope_ref"]


def test_multiple_or_code_mode_python_entries_are_not_treated_as_a_release(tmp_path, monkeypatch):
    home, root, git = prepare(tmp_path, monkeypatch)
    label = probe.LABELS[0][1]
    plist = home / "Library/LaunchAgents" / (label + ".plist")
    for args in (
        ["/usr/bin/python3", "/a/one.py", "/b/two.py"],
        ["/usr/bin/python3", "-c", "/a/one.py"],
        ["/usr/bin/python3", "../a/one.py"],
    ):
        plist.write_bytes(plistlib.dumps({"Label":label,"ProgramArguments":args}))
        r=probe.release_inventory(home=home,root=root,git_run=git)
        assert r["status"] == "BLOCKED"
        assert r["failed_stage"] == "OPERATOR_SOURCE_BINDING"
        assert r["release_permitted"] is False



def test_operator_only_scope_bindings_stable_and_guard_gated(tmp_path, monkeypatch):
    from ai_foundation.release_gate import GuardReleaseGate
    from ai_foundation.store import SQLiteGuardStore
    from ai_foundation.guard import GuardCore
    from ai_foundation.core import GuardState
    from ai_foundation.productization import FoundationConfig
    home, root, original_git = prepare(tmp_path, monkeypatch)
    for relative in ("src/ai_foundation/human_model_context.py",
                     "src/ai_foundation/mcp_owner_grants.py",
                     "src/ai_foundation/release_gate.py"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pinned:" + relative)
    label = probe.LABELS[0][1]
    plist = home / "Library/LaunchAgents" / (label + ".plist")
    cfg = home / "config.json"
    cfg.write_text('{"data_dir":"/private/existing"}')
    row = plistlib.loads(plist.read_bytes())
    row["ProgramArguments"] += ["--config", str(cfg)]
    plist.write_bytes(plistlib.dumps(row))
    def git(args, **kw):
        if args[-2:] == ["rev-parse", "HEAD"]:
            return original_git(args, **kw)
        assert args[-3:] == ["status", "--porcelain", "--untracked-files=no"]
        return subprocess.CompletedProcess(args, 0, "", "")
    scope, receipt = probe.operator_only_release_scope(home=home, root=root, git_run=git)
    assert receipt["status"] == "OBSERVED"
    assert receipt["operator_only"] is True
    assert len(scope.scope_ref) == 64
    assert receipt["scope_ref"] == scope.scope_ref
    assert receipt["release_permitted"] is False
    assert receipt["rollback_backup_verified"] is False
    assert receipt["guard_owner_approval_verified"] is False
    assert receipt["service_mutations"] == receipt["native_dispatches"] == 0
    assert "local9b" not in str(scope.as_dict()).lower()
    assert str(home) not in json.dumps(receipt)
    # Existing GuardReleaseGate records a PENDING request, not an approval
    data = tmp_path / "guard"
    data.mkdir()
    cfg2 = FoundationConfig(str(data.resolve()))
    store = SQLiteGuardStore(data / cfg2.guard_db)
    GuardCore(store.load(), store=store)
    gate = GuardReleaseGate(store, tmp_path / "release-registry.json")
    waiting = gate.prepare(scope, canon_revision="canon-fixture-reviewed-v1",
                           run_id="operator-p4-fixture")
    assert waiting["status"] == "WAITING_HUMAN"
    assert gate.verify(scope, "operator-p4-fixture",
                       waiting["request_ref"])["status"] == "OWNER_APPROVAL_REQUIRED"
    assert receipt["release_permitted"] is False
    (root / "src/ai_foundation/human_model_context.py").write_text("changed")
    changed, record = probe.operator_only_release_scope(home=home, root=root, git_run=git)
    assert changed is not None and record["scope_ref"] != receipt["scope_ref"]
    assert gate.verify(changed, "operator-p4-fixture",
                       waiting["request_ref"])["status"] == "RELEASE_SCOPE_MISMATCH"


def test_operator_only_scope_never_promotes_dirty_or_unbound_install(tmp_path, monkeypatch):
    home, root, original_git = prepare(tmp_path, monkeypatch)
    for relative in ("src/ai_foundation/human_model_context.py",
                     "src/ai_foundation/mcp_owner_grants.py",
                     "src/ai_foundation/release_gate.py"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pinned")
    def dirty(args, **kw):
        if args[-2:] == ["rev-parse", "HEAD"]:
            return original_git(args, **kw)
        return subprocess.CompletedProcess(args, 0, " M source\n", "")
    scope, result = probe.operator_only_release_scope(
        home=home, root=root, git_run=dirty)
    assert scope is None and result["stage"] == "WORKTREE"
    assert result["release_permitted"] is False
    def clean(args, **kw):
        if args[-2:] == ["rev-parse", "HEAD"]:
            return original_git(args, **kw)
        return subprocess.CompletedProcess(args, 0, "", "")
    scope, result = probe.operator_only_release_scope(
        home=home, root=root, git_run=clean)
    assert scope is None and result["stage"] == "INSTALLED_OPERATOR"
    assert result["scope_ref"] is None and result["guard_mutations"] == 0



def test_changed_owner_config_changes_operator_only_scope(tmp_path, monkeypatch):
    home, root, original_git = prepare(tmp_path, monkeypatch)
    for relative in ("src/ai_foundation/human_model_context.py",
                     "src/ai_foundation/mcp_owner_grants.py",
                     "src/ai_foundation/release_gate.py"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("candidate:" + relative)
    label = probe.LABELS[0][1]
    plist = home / "Library/LaunchAgents" / (label + ".plist")
    cfg = home / "config.json"
    cfg.write_text('{"data_dir":"/private/old"}')
    values=plistlib.loads(plist.read_bytes())
    values["ProgramArguments"] += ["--config", str(cfg)]
    plist.write_bytes(plistlib.dumps(values))
    def git(args, **kw):
        if args[-2:] == ["rev-parse", "HEAD"]:
            return original_git(args, **kw)
        return subprocess.CompletedProcess(args,0,"","")
    scope, first=probe.operator_only_release_scope(home=home,root=root,git_run=git)
    assert scope is not None and first["status"]=="OBSERVED"
    cfg.write_text('{"data_dir":"/private/changed"}')
    next_scope, second=probe.operator_only_release_scope(home=home,root=root,git_run=git)
    assert next_scope is not None and next_scope.scope_ref != scope.scope_ref
    assert second["release_permitted"] is False


def test_operator_live_preflight_reads_launchd_pid_and_idle_without_effects(monkeypatch, tmp_path):
    monkeypatch.setattr(probe, "require_m1", lambda: None)
    observations = []
    class Fixed:
        def __init__(self, root, *, home=None):
            observations.append(("constructed", root, home))
        def _registered(self):
            observations.append("launchctl_print")
            return True
        def _pid_owned(self):
            observations.append("lsof_pid")
            return True
        def _human(self):
            observations.append("loopback_operator_read")
            return {"activity": [], "state": "FAILED",
                    "private": "SECRET_FIXTURE"}
    report = probe.operator_live_preflight(
        root=tmp_path/"source", home=tmp_path/"owner", host_factory=Fixed)
    assert report["status"] == "OBSERVED"
    assert report["preflight_prerequisites_observed"] is True
    assert report["operator_idle"] is True
    assert report["guard_owner_approval_verified"] is False
    assert report["service_mutations"] == report["model_calls"] == report["native_dispatches"] == 0
    assert observations[1:] == ["launchctl_print", "lsof_pid", "loopback_operator_read"]
    assert "SECRET_FIXTURE" not in json.dumps(report)


def test_operator_live_preflight_keeps_unknown_and_busy_separate(monkeypatch, tmp_path):
    monkeypatch.setattr(probe, "require_m1", lambda: None)
    class NoRead:
        def __init__(self, *args, **kwargs): pass
        def _registered(self): return True
        def _pid_owned(self): return False
        def _human(self): raise AssertionError("No HTTP call when no PID bound")
    result = probe.operator_live_preflight(host_factory=NoRead)
    assert result["status"] == "OBSERVED"
    assert result["operator_http_readable"] is False
    assert result["operator_idle"] is None
    assert result["preflight_prerequisites_observed"] is False
    class Busy(NoRead):
        def _pid_owned(self): return True
        def _human(self): return {"activity": [{"function": "CODE"}]}
    busy = probe.operator_live_preflight(host_factory=Busy)
    assert busy["operator_idle"] is False
    assert busy["preflight_prerequisites_observed"] is False


def test_operator_live_preflight_exception_is_redacted_without_approval(monkeypatch):
    monkeypatch.setattr(probe, "require_m1", lambda: None)
    class Bad:
        def __init__(self, *args, **kwargs): pass
        def _registered(self): raise ValueError("SECRET_OWNER_PATH")
    r = probe.operator_live_preflight(host_factory=Bad)
    assert r["status"] == "UNVERIFIED"
    assert r["preflight_prerequisites_observed"] is False
    assert r["guard_owner_approval_verified"] is False
    assert "SECRET_OWNER_PATH" not in json.dumps(r)
