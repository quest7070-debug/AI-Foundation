"""Disposable-only Operator release host. Never opens installed M1 Guard."""
import pytest
from ai_foundation.operator_release_transaction import (
    OperatorOnlyCutover, ReleaseDenied, ManualRecoveryRequired)
from ai_foundation.release_gate import GuardReleaseGate, ImmutableReleaseScope
from ai_foundation.guard import GuardCore
from ai_foundation.productization import FoundationConfig
from ai_foundation.store import SQLiteGuardStore


class FakeHost:
    def __init__(self, ref):
        self.ref = ref
        self.actions = []
        self.backup_ok = True
        self.candidate_ok = True
        self.live_ok = True
        self.rollback_ok = True
        self.switch_error = False
    def current_scope_ref(self):
        self.actions.append("scope")
        return self.ref
    def backup_prior(self, scope):
        self.actions.append("backup")
    def verify_backup(self, scope):
        self.actions.append("verify_backup")
        return self.backup_ok
    def stage_candidate(self, scope):
        self.actions.append("stage")
    def verify_candidate(self, scope):
        self.actions.append("verify_candidate")
        return self.candidate_ok
    def switch_operator(self, scope):
        self.actions.append("switch")
        if self.switch_error:
            raise RuntimeError("simulated switch failure")
    def readback_operator(self, scope):
        self.actions.append("readback")
        return self.live_ok
    def rollback_operator(self, scope):
        self.actions.append("rollback")
    def verify_rollback(self, scope):
        self.actions.append("verify_rollback")
        return self.rollback_ok


class Owner:
    def __init__(self, accepted):
        self.accepted = accepted
    def verify_exact_release(self, scope, run, request_ref):
        return self.accepted


def setup(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    config = FoundationConfig(str(root.resolve()))
    store = SQLiteGuardStore(root / config.guard_db)
    GuardCore(store.load(), store=store)
    scope = ImmutableReleaseScope(
        path="m1-operator", source_sha="a"*64,
        previous_authority="installed-prior",
        previous_endpoint="launchd:operator",
        candidate_authority="reviewed-fixed-head",
        candidate_endpoint="launchd:operator-new",
        rollback_procedure="restore previous",
        switch_target="operator-only",
        readback_target="pid-bound-current",
        rollback_readback_target="pid-bound-previous")
    gate = GuardReleaseGate(store, tmp_path / "cutover-registry.json")
    request = gate.prepare(scope, run_id="release-p4", canon_revision="fixture-canon")
    return store, scope, gate, request["request_ref"]


def test_guard_and_owner_are_independent_and_default_denies(tmp_path):
    store, scope, gate, ref = setup(tmp_path)
    host = FakeHost(scope.scope_ref)
    with pytest.raises(ReleaseDenied, match="GATE_UNAVAILABLE"):
        OperatorOnlyCutover(gate, host).execute(scope, "release-p4", ref)
    with pytest.raises(ReleaseDenied, match="GUARD"):
        OperatorOnlyCutover(gate, host, Owner(True)).execute(scope, "release-p4", ref)
    assert store.approve_pending("release-p4", ref)
    with pytest.raises(ReleaseDenied, match="HOST_OWNER"):
        OperatorOnlyCutover(gate, host, Owner(False)).execute(scope, "release-p4", ref)
    assert host.actions == ["scope", "scope"]


def test_valid_exact_fixture_cutover(tmp_path):
    store, scope, gate, ref = setup(tmp_path)
    assert store.approve_pending("release-p4", ref)
    host = FakeHost(scope.scope_ref)
    result = OperatorOnlyCutover(gate, host, Owner(True)).execute(
        scope, "release-p4", ref)
    assert result.status == "VERIFIED" and result.operator_only
    assert gate.registry.get(scope.path).status == "VERIFIED"
    assert host.actions == [
        "scope", "backup", "verify_backup", "stage", "verify_candidate",
        "scope", "switch", "readback"]


@pytest.mark.parametrize("attribute", ["backup_ok", "candidate_ok"])
def test_no_service_effect_without_verified_backup_or_candidate(tmp_path, attribute):
    store, scope, gate, ref = setup(tmp_path)
    assert store.approve_pending("release-p4", ref)
    host = FakeHost(scope.scope_ref)
    setattr(host, attribute, False)
    with pytest.raises(ReleaseDenied):
        OperatorOnlyCutover(gate, host, Owner(True)).execute(
            scope, "release-p4", ref)
    assert "switch" not in host.actions
    assert gate.registry.get(scope.path).status == "PREPARED"


@pytest.mark.parametrize("switch_error,live", [(True, True), (False, False)])
def test_switch_or_readback_failure_rolls_back(tmp_path, switch_error, live):
    store, scope, gate, ref = setup(tmp_path)
    assert store.approve_pending("release-p4", ref)
    host = FakeHost(scope.scope_ref)
    host.switch_error, host.live_ok = switch_error, live
    with pytest.raises((ReleaseDenied, RuntimeError)):
        OperatorOnlyCutover(gate, host, Owner(True)).execute(
            scope, "release-p4", ref)
    assert "rollback" in host.actions and "verify_rollback" in host.actions
    assert gate.registry.get(scope.path).status == "ROLLED_BACK"


def test_failed_rollback_leaves_recoverable_cutover_state(tmp_path):
    store, scope, gate, ref = setup(tmp_path)
    assert store.approve_pending("release-p4", ref)
    host = FakeHost(scope.scope_ref)
    host.live_ok = False
    host.rollback_ok = False
    with pytest.raises(ManualRecoveryRequired):
        OperatorOnlyCutover(gate, host, Owner(True)).execute(
            scope, "release-p4", ref)
    assert gate.registry.get(scope.path).status == "CUTOVER"


def test_changed_scope_stale_request_and_wrong_service_never_change_host(tmp_path):
    store, scope, gate, ref = setup(tmp_path)
    assert store.approve_pending("release-p4", ref)
    host = FakeHost("b"*64)
    with pytest.raises(ReleaseDenied, match="SCOPE"):
        OperatorOnlyCutover(gate, host, Owner(True)).execute(scope,"release-p4",ref)
    assert host.actions == ["scope"]
    host.ref = scope.scope_ref
    with pytest.raises(ReleaseDenied, match="GUARD"):
        OperatorOnlyCutover(gate, host, Owner(True)).execute(
            scope, "release-p4", "f"*64)
    assert "backup" not in host.actions
    changed = ImmutableReleaseScope(**{**scope.as_dict(),"path":"local9b"})
    with pytest.raises(ReleaseDenied, match="OPERATOR_ONLY"):
        OperatorOnlyCutover(gate, host, Owner(True)).execute(changed,"release-p4",ref)



def test_failed_verified_receipt_also_restores_previous_operator(tmp_path):
    store, scope, gate, ref = setup(tmp_path)
    assert store.approve_pending("release-p4", ref)
    host = FakeHost(scope.scope_ref)
    original = gate.registry.transition
    def break_final_receipt(path, old, new):
        if new == "VERIFIED":
            raise RuntimeError("synthetic durable receipt failure")
        return original(path, old, new)
    gate.registry.transition = break_final_receipt
    with pytest.raises(RuntimeError, match="receipt"):
        OperatorOnlyCutover(gate, host, Owner(True)).execute(
            scope, "release-p4", ref)
    assert "rollback" in host.actions
    assert gate.registry.get(scope.path).status == "ROLLED_BACK"


def test_owner_gate_revoked_during_stage_never_switches(tmp_path):
    store, scope, gate, ref = setup(tmp_path)
    assert store.approve_pending("release-p4", ref)
    host = FakeHost(scope.scope_ref)
    class RevokedOwner:
        seen = 0
        def verify_exact_release(self, scope, run, request_ref):
            self.seen += 1
            return self.seen == 1
    owner = RevokedOwner()
    with pytest.raises(ReleaseDenied, match="HOST_OWNER"):
        OperatorOnlyCutover(gate, host, owner).execute(
            scope, "release-p4", ref)
    assert "stage" in host.actions and "switch" not in host.actions
    assert gate.registry.get(scope.path).status == "PREPARED"
