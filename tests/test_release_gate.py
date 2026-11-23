"""Guard/owner-approved immutable release+rollback gate. Synthetic SQLite only."""
import pytest

from ai_foundation.guard import GuardCore
from ai_foundation.productization import FoundationConfig
from ai_foundation.release_gate import GuardReleaseGate, ImmutableReleaseScope
from ai_foundation.store import SQLiteGuardStore


def setup(tmp_path, registry_name="release-cutover.json"):
    root = tmp_path / "data"
    root.mkdir(exist_ok=True)
    config = FoundationConfig(str(root.resolve()))
    store = SQLiteGuardStore(root / config.guard_db)
    GuardCore(store.load(), store=store)
    scope = ImmutableReleaseScope(
        path="m1-operator",
        source_sha="0398e1e84a22b1fb02b8c5afea9b85e4317a3e35",
        previous_authority="installed-operator",
        previous_endpoint="launchd:dev.quest7070.ai-foundation.operator",
        candidate_authority="reviewed-main",
        candidate_endpoint="launchd:dev.quest7070.ai-foundation.operator",
        rollback_procedure="restore preserved release archive and prior launchd plist; read back /health and /api/human",
        switch_target="launchctl-bootstrap-operator",
        readback_target="operator-health-and-human-state",
        rollback_readback_target="operator-rollback-health",
    )
    gate = GuardReleaseGate(store, tmp_path / registry_name)
    return store, scope, gate


def test_scope_is_immutable_and_changes_ref(tmp_path):
    _, scope, _ = setup(tmp_path)
    with pytest.raises(AttributeError):
        scope.source_sha = "x"
    changed = ImmutableReleaseScope(**{**scope.as_dict(), "source_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})
    assert scope.scope_ref != changed.scope_ref


def test_prepare_requires_owner_approval_and_verifies_exact_scope(tmp_path):
    store, scope, gate = setup(tmp_path)
    prepared = gate.prepare(scope, canon_revision="canon-test-v4", run_id="release-1")
    assert prepared["ok"] and prepared["status"] == "WAITING_HUMAN"
    assert prepared["release_permitted"] is False
    pending = gate.verify(scope, "release-1", prepared["request_ref"], require_approved=False)
    assert pending["ok"] and not pending["approved"]
    blocked = gate.verify(scope, "release-1", prepared["request_ref"])
    assert not blocked["ok"] and blocked["status"] == "OWNER_APPROVAL_REQUIRED"
    # Simulate the separately authenticated Operator/Guard decision boundary.
    # The release gate itself has no API to grant approval.
    assert not hasattr(gate, "approve")
    assert store.approve_pending("release-1", prepared["request_ref"])
    approved = gate.verify(scope, "release-1", prepared["request_ref"])
    assert approved["approved"] and approved["status"] == "APPROVED"
    assert approved["release_permitted"] is False and approved["service_mutations"] == 0
    assert store.is_approved_for("release-1", "production_deploy",
                                 "release-scope:" + scope.scope_ref, "canon-test-v4",
                                 "release:" + scope.scope_ref)


def test_changed_source_or_stale_ref_cannot_authorize(tmp_path):
    store, scope, gate = setup(tmp_path)
    prepared = gate.prepare(scope, canon_revision="canon-test-v4", run_id="release-2")
    old_ref = prepared["request_ref"]
    changed = ImmutableReleaseScope(**{**scope.as_dict(), "source_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"})
    assert gate.verify(changed, "release-2", old_ref, require_approved=False)["status"] == "RELEASE_SCOPE_MISMATCH"
    # A different immutable scope cannot reuse the old Guard approval/request.
    assert gate.verify(changed, "release-2", old_ref)["status"] == "RELEASE_SCOPE_MISMATCH"
    # The original pending request remains valid for the original immutable
    # scope unless explicitly consumed/cancelled; callers must never reuse it
    # after scope change.
    assert store.approve_pending("release-2", old_ref)
    assert gate.verify(scope, "release-2", old_ref)["approved"]
    # A new release scope on the same service path requires an explicit new
    # registry generation after rollback/cutover handling, not silent overwrite.
    with pytest.raises(ValueError):
        gate.prepare(changed, canon_revision="canon-test-v4", run_id="release-2b")
    gate2 = GuardReleaseGate(store, tmp_path / "release-cutover-v2.json")
    changed_path = ImmutableReleaseScope(**{**scope.as_dict(),
        "path": "m1-operator-candidate", "source_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"})
    reprep = gate2.prepare(changed_path, canon_revision="canon-test-v4", run_id="release-2b")
    assert old_ref != reprep["request_ref"]
    assert store.approve_pending("release-2b", reprep["request_ref"])
    assert gate2.verify(changed_path, "release-2b", reprep["request_ref"])["approved"]


def test_replay_after_approval_fails_closed(tmp_path):
    store, scope, gate = setup(tmp_path)
    prepared = gate.prepare(scope, canon_revision="canon-test-v4", run_id="release-3")
    assert store.approve_pending("release-3", prepared["request_ref"])
    # Approval is single-use at the existing Guard boundary, not this gate.
    assert not store.approve_pending("release-3", prepared["request_ref"])
    with_gate = GuardReleaseGate(gate.store, tmp_path / "release-cutover.json")
    assert with_gate.verify(scope, "release-3", prepared["request_ref"])["approved"]
    # The pending ref is not an authority bearer; never accept substituted refs.
    assert with_gate.verify(scope, "release-3", "f" * 64)["status"] == "REQUEST_REF_MISMATCH"


def test_registry_persists_rollback_contract_without_service_effect(tmp_path):
    _, scope, gate = setup(tmp_path)
    prepared = gate.prepare(scope, canon_revision="canon-test-v4", run_id="release-4")
    rec = gate.registry.get(scope.path)
    assert rec is not None
    assert rec.rollback_procedure == scope.rollback_procedure
    assert rec.release_scope_ref == scope.scope_ref
    assert rec.rollback_readback_target == scope.rollback_readback_target
    assert rec.release_run_id == "release-4"
    assert rec.release_request_ref == prepared["request_ref"]


def test_release_ref_cannot_self_authorize(tmp_path):
    store, scope, gate = setup(tmp_path)
    prepared = gate.prepare(scope, canon_revision="canon-test-v4", run_id="release-5")
    assert not hasattr(gate, "approve")
    assert not store.is_approved("release-5")
    assert gate.verify(scope, "release-5", "a" * 64)["status"] == "REQUEST_REF_MISMATCH"
    assert gate.verify(scope, "release-5", prepared["request_ref"])["status"] == "OWNER_APPROVAL_REQUIRED"
    assert not store.is_approved("release-5")


def test_requires_real_explicit_canon_binding(tmp_path):
    store, scope, gate = setup(tmp_path)
    with pytest.raises(ValueError, match="Canon revision"):
        gate.prepare(scope, run_id="release-unbound")
    with pytest.raises(ValueError, match="synthetic Canon"):
        gate.prepare(scope, run_id="release-unbound",
                     canon_revision="release-gate/v1")
    assert not store.is_approved("release-unbound")
    assert gate.registry.get(scope.path) is None


def test_new_release_generation_requires_verified_predecessor_and_fresh_approval(tmp_path):
    store, incumbent, gate = setup(tmp_path)
    first = gate.prepare(incumbent, canon_revision="canon-test-v4", run_id="release-old")
    assert store.approve_pending("release-old", first["request_ref"])
    gate.registry.transition(incumbent.path, "PREPARED", "CUTOVER")
    gate.registry.transition(incumbent.path, "CUTOVER", "VERIFIED")
    new = ImmutableReleaseScope(**{
        **incumbent.as_dict(),
        "source_sha": "b" * 40,
        "candidate_authority": "github-commit:" + "b" * 40,
    })
    # A previous verified release is not replay authority. We will not mint
    # a new Guard request until an independent M1 loaded-source check names
    # the precise incumbent release scope.
    for predecessor in (None, "f" * 64, new.scope_ref):
        with pytest.raises(ValueError, match="incumbent"):
            gate.prepare(new, run_id="release-new", canon_revision="canon-test-v4",
                         verified_predecessor_ref=predecessor)
        assert not store.is_approved("release-new")
    second = gate.prepare(new, run_id="release-new", canon_revision="canon-test-v4",
                          verified_predecessor_ref=incumbent.scope_ref)
    assert second["status"] == "WAITING_HUMAN"
    assert not store.is_approved("release-new")
    assert gate.verify(new, "release-new", second["request_ref"])["status"] == (
        "OWNER_APPROVAL_REQUIRED")
    latest = gate.registry.get(new.path)
    assert latest.status == "PREPARED" and latest.generation == 2
    history = gate.registry.history(new.path)
    assert any(row.status == "VERIFIED" and
               row.release_scope_ref == incumbent.scope_ref for row in history)
    assert latest.release_scope_ref == new.scope_ref
