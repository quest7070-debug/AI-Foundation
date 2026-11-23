from contextlib import contextmanager
from dataclasses import replace
import time
from hashlib import sha256
import os

import unittest
import tempfile
from pathlib import Path

from ai_foundation.core import CanonContract, Decision, EffectStatus, GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.guarded_maintenance import GuardedMaintenance, ReviewedMaintenanceIntent
from ai_foundation.store import SQLiteGuardStore, approval_request_ref


class FixtureLease:
    """Synthetic scope proof only; not production host-lease acceptance."""
    def __init__(self): self.held = 0
    @contextmanager
    def hold(self):
        self.held += 1
        try: yield
        finally: self.held -= 1


class FixturePolicy:
    def authorize(self, plan):
        return Decision.ALLOW if plan.policy_revision == "c" * 64 else Decision.DENY


class FixturePort:
    """A generated public state marker; no host paths, commands or personal data."""
    def __init__(self, intent, lease):
        self.intent_digest = intent.digest
        self.data_scope = intent.data_scope
        self.intent, self.lease = intent, lease
        self.state, self.calls, self.fail_after, self.on_effect = intent.before_fingerprint, 0, False, None
    def observe(self):
        assert self.lease.held == 1
        return self.state
    def execute(self):
        assert self.lease.held == 1
        self.calls += 1
        self.state = self.intent.after_fingerprint
        if self.on_effect: self.on_effect()
        if self.fail_after: raise OSError("synthetic lost response")


def fixture(tmp_path):
    intent = ReviewedMaintenanceIntent("restart-reviewed-service", "foundation_operator", "generated-fixture",
        "a" * 64, "b" * 64, "fixture-v1", "c" * 64, "d" * 32)
    store = SQLiteGuardStore(tmp_path / "generated-authority.sqlite")
    guard = GuardCore(store.runtime_state(), store=store, policy_boundary=FixturePolicy())
    lease = FixtureLease()
    port = FixturePort(intent, lease)
    return intent, store, guard, lease, port, GuardedMaintenance(
        intent, CanonContract("generated-fixture", "fixture-v1"), guard, port, lease)


def approve_exact_fixture(store, runner, run_id):
    """Apply only the current durable exact-plan approval handshake in a synthetic fixture."""
    if not store.has_pending(run_id):
        assert runner.execute() == "WAITING_HUMAN"
    with store._connect() as db:
        row = db.execute(
            "SELECT action, target, request_nonce, canon_revision, effect_id "
            "FROM approval_requests WHERE run_id=?", (run_id,)
        ).fetchone()
    assert row is not None, "no durable pending exact-plan review"
    assert store.approve_pending(run_id, approval_request_ref(run_id, *row))
    assert store.is_approved_for(run_id, row[0], row[1], row[3], row[4])


class GuardedMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="generated-maintenance-")
        self.addCleanup(self.temporary.cleanup)
        self.tmp_path = Path(self.temporary.name)

    def test_missing_approval_has_zero_effects_and_no_auto_approval(self):
        tmp_path = self.tmp_path
        intent, store, guard, lease, port, runner = fixture(tmp_path)
        assert runner.execute() == "WAITING_HUMAN"
        assert port.calls == 0 and lease.held == 0
        assert not store.is_approved(intent.run_id)
        assert store.get_effect(intent.run_id) is None
        assert runner.describe()["guard_action"] == "production_deploy"

    def test_durable_approval_single_execution_restart_readback_and_no_replay(self):
        tmp_path = self.tmp_path
        intent, store, guard, lease, port, runner = fixture(tmp_path)
        approve_exact_fixture(store, runner, intent.run_id)  # fixture authority only; no production approval
        assert runner.execute() == "VERIFIED_COMPLETE"
        assert store.get_effect(intent.run_id).status is EffectStatus.VERIFIED
        reopened = GuardCore(store.runtime_state(), store=store, policy_boundary=FixturePolicy())
        second = GuardedMaintenance(intent, CanonContract("generated-fixture", "fixture-v1"), reopened, port, lease)
        assert second.execute() == "VERIFIED_COMPLETE" and port.calls == 1 and lease.held == 0
        port.state = "e" * 64
        assert second.execute() == "VERIFIED_EFFECT_TARGET_DRIFT" and port.calls == 1

    def test_changed_review_cannot_reuse_approval(self):
        for i, change in enumerate([{"target":"llama_swap"},{"operation":"rollback-reviewed-release"},{"after_fingerprint":"e"*64},{"nonce":"e"*32}]):
            with self.subTest(change=change):
                tmp_path = self.tmp_path / str(i)
                tmp_path.mkdir()
                intent, store, guard, lease, port, runner = fixture(tmp_path)
                approve_exact_fixture(store, runner, intent.run_id)
                changed = replace(intent, **change)
                other_port = FixturePort(changed, lease)
                other = GuardedMaintenance(changed, CanonContract("generated-fixture", "fixture-v1"), guard, other_port, lease)
                assert other.execute() == "WAITING_HUMAN" and other_port.calls == 0

    def test_current_state_conflict_and_target_lease_do_not_execute(self):
        tmp_path = self.tmp_path
        intent, store, guard, lease, port, runner = fixture(tmp_path)
        approve_exact_fixture(store, runner, intent.run_id)
        port.state = "e" * 64
        assert runner.execute() == "TARGET_PRECONDITION_CONFLICT" and port.calls == 0
        port.state = intent.before_fingerprint
        assert store.try_claim_target("maintenance:foundation_operator", "fixture-other-owner", time.time(), 60)
        assert runner.execute() == "TARGET_IN_PROGRESS" and port.calls == 0 and lease.held == 0

    def test_uncertainty_survives_reopen_and_only_observe_reconciliation_completes(self):
        tmp_path = self.tmp_path
        intent, store, guard, lease, port, runner = fixture(tmp_path)
        approve_exact_fixture(store, runner, intent.run_id)
        port.fail_after = True
        assert runner.execute() == "UNCERTAIN_RECONCILE_REQUIRED"
        assert store.get_effect(intent.run_id).status is EffectStatus.UNCERTAIN
        reopened = GuardCore(store.runtime_state(), store=store, policy_boundary=FixturePolicy())
        second = GuardedMaintenance(intent, CanonContract("generated-fixture", "fixture-v1"), reopened, port, lease)
        assert second.execute() == "UNCERTAIN_RECONCILE_REQUIRED" and port.calls == 1
        assert second.reconcile() == "VERIFIED_COMPLETE" and port.calls == 1

    def test_cancellation_before_or_during_effect_never_retries(self):
        tmp_path = self.tmp_path
        intent, store, guard, lease, port, runner = fixture(tmp_path)
        approve_exact_fixture(store, runner, intent.run_id)
        guard.cancel(intent.run_id)
        assert runner.execute() == "DENY" and port.calls == 0
        # A distinct generated fixture represents a different independently approved review.
        changed = replace(intent, nonce="e" * 32)
        other_port = FixturePort(changed, lease)
        other = GuardedMaintenance(changed, CanonContract("generated-fixture", "fixture-v1"), guard, other_port, lease)
        approve_exact_fixture(store, other, changed.run_id)
        other_port.on_effect = lambda: guard.cancel(changed.run_id)
        assert other.execute() == "CANCELLED_RECONCILE_REQUIRED"
        assert other.execute() == "UNCERTAIN_RECONCILE_REQUIRED" and other_port.calls == 1
        assert other.reconcile() == "VERIFIED_COMPLETE" and other_port.calls == 1

    def test_unverified_bindings_and_changed_port_are_rejected(self):
        tmp_path = self.tmp_path
        intent, store, guard, lease, port, runner = fixture(tmp_path)
        with self.assertRaisesRegex(ValueError, "DURABLE_GUARD"):
            GuardedMaintenance(intent, CanonContract("generated-fixture", "fixture-v1"), GuardCore(GuardState()), port, lease)
        port.intent_digest = "e" * 64
        with self.assertRaisesRegex(ValueError, "HOST_PORT_BINDING"):
            runner.execute()
        assert port.calls == 0

    def test_personal_data_scope_and_other_canon_are_excluded(self):
        intent, store, guard, lease, port, runner = fixture(self.tmp_path)
        with self.assertRaisesRegex(ValueError, "PERSONAL_DATA_SCOPE_EXCLUDED"):
            replace(intent, data_scope="PERSONAL_DATA")
        with self.assertRaisesRegex(ValueError, "CANON_SOURCE_MISMATCH"):
            GuardedMaintenance(intent, CanonContract("other", "fixture-v1"), guard, port, lease)
        port.data_scope = "PERSONAL_DATA"
        with self.assertRaisesRegex(ValueError, "HOST_PORT_BINDING"):
            runner.execute()
        assert port.calls == 0 and store.get_effect(intent.run_id) is None

    def test_generated_code_activation_and_rollback_use_real_atomic_readback(self):
        # Newly generated code only: no production/user directory or DB is opened.
        old, new = b"VERSION = 1\n", b"VERSION = 2\n"
        before, after = sha256(old).hexdigest(), sha256(new).hexdigest()
        active = self.tmp_path / "generated-code.py"
        active.write_bytes(old)
        intent, store, guard, lease, _, _ = fixture(self.tmp_path)
        deploy = replace(intent, operation="activate-reviewed-release",
                         before_fingerprint=before, after_fingerprint=after)
        class FilePort:
            data_scope = "NON_PERSONAL_RUNTIME_ONLY"
            def __init__(self, reviewed, payload):
                self.intent_digest, self.payload = reviewed.digest, payload
            def execute(self):
                assert lease.held == 1
                stage = active.with_suffix(".staged")
                stage.write_bytes(self.payload)
                os.replace(stage, active)
            def observe(self):
                assert lease.held == 1
                return sha256(active.read_bytes()).hexdigest()
        def bound(reviewed, payload):
            return GuardedMaintenance(reviewed, CanonContract("generated-fixture", "fixture-v1"),
                                      guard, FilePort(reviewed, payload), lease)
        forward = bound(deploy, new)
        assert forward.execute() == "WAITING_HUMAN" and active.read_bytes() == old
        approve_exact_fixture(store, forward, deploy.run_id)
        assert forward.execute() == "VERIFIED_COMPLETE" and active.read_bytes() == new
        rollback = replace(deploy, operation="rollback-reviewed-release", nonce="f" * 32,
                           before_fingerprint=after, after_fingerprint=before)
        backward = bound(rollback, old)
        assert backward.execute() == "WAITING_HUMAN" and active.read_bytes() == new
        approve_exact_fixture(store, backward, rollback.run_id)
        assert backward.execute() == "VERIFIED_COMPLETE" and active.read_bytes() == old
        assert store.get_effect(deploy.run_id).status is EffectStatus.VERIFIED
        assert store.get_effect(rollback.run_id).status is EffectStatus.VERIFIED
        assert not active.with_suffix(".staged").exists()

    def test_canon_and_policy_drift_keep_existing_guard_veto(self):
        tmp_path = self.tmp_path
        intent, store, guard, lease, port, runner = fixture(tmp_path)
        approve_exact_fixture(store, runner, intent.run_id)
        wrong_canon = GuardedMaintenance(intent, CanonContract("generated-fixture", "other-revision"), guard, port, lease)
        assert wrong_canon.execute() == "WAITING_HUMAN" and port.calls == 0
        changed = replace(intent, policy_revision="e" * 64)
        other_port = FixturePort(changed, lease)
        other = GuardedMaintenance(changed, CanonContract("generated-fixture", "fixture-v1"), guard, other_port, lease)
        # A changed policy must be vetoed before any new approval is issued.
        assert other.execute() == "DENY" and other_port.calls == 0

    def test_intent_requires_distinct_generation_and_fixed_nonpersonal_target(self):
        args = ("restart-reviewed-service", "foundation_operator", "generated-fixture", "a" * 64, "a" * 64,
                "fixture-v1", "c" * 64, "d" * 32)
        with self.assertRaisesRegex(ValueError, "DISTINCT_GENERATION"):
            ReviewedMaintenanceIntent(*args)
        with self.assertRaisesRegex(ValueError, "TARGET_INVALID"):
            ReviewedMaintenanceIntent("restart-reviewed-service", "/personal-data", "generated-fixture", "a" * 64, "b" * 64,
                                      "fixture-v1", "c" * 64, "d" * 32)


if __name__ == "__main__":
    unittest.main()
