from ai_foundation.core import (
    CanonContract,
    EffectIntent,
    EffectStatus,
    GuardState,
    TaskPlan,
)
from ai_foundation.guard import GuardCore
from ai_foundation.operator_actions import OperatorActions


class Port:
    def __init__(self, observed):
        self.observed = observed
        self.execute_count = 0

    def execute(self, plan):
        self.execute_count += 1
        raise AssertionError("operator reconciliation must never execute")

    def observe(self, plan):
        return self.observed


def test_operator_approval_and_cancel_use_guard_boundary():
    state = GuardState()
    guard = GuardCore(state)

    actions = OperatorActions(guard)

    assert actions.approve_run("run-1").ok
    assert "run-1" in state.approvals

    assert actions.cancel_run("run-2").ok
    assert "run-2" in state.cancellations


def test_operator_reconcile_is_observe_only():
    effect = EffectIntent(
        "effect-1",
        "run-1",
        "target",
        "done",
        EffectStatus.UNCERTAIN,
    )

    state = GuardState(effects={"effect-1": effect})
    guard = GuardCore(state)

    port = Port("done")
    plan = TaskPlan(
        run_id="run-1",
        effect_id="effect-1",
        action="send_email",
        target="target",
    )

    result = OperatorActions(guard).reconcile_effect(
        "effect-1",
        plan,
        port,
    )

    assert result.ok
    assert result.status == "VERIFIED_COMPLETE"
    assert effect.status is EffectStatus.VERIFIED
    assert port.execute_count == 0


def test_operator_reconcile_mismatch_stays_uncertain():
    effect = EffectIntent(
        "effect-1",
        "run-1",
        "target",
        "expected",
        EffectStatus.UNCERTAIN,
    )

    state = GuardState(effects={"effect-1": effect})
    guard = GuardCore(state)

    port = Port("different")
    plan = TaskPlan(
        run_id="run-1",
        effect_id="effect-1",
        action="send_email",
        target="target",
    )

    result = OperatorActions(guard).reconcile_effect(
        "effect-1",
        plan,
        port,
    )

    assert not result.ok
    assert result.status == "WAITING_HUMAN_UNCERTAIN_EFFECT"
    assert effect.status is EffectStatus.UNCERTAIN
    assert port.execute_count == 0

def test_operator_approval_is_durable(tmp_path):
    from ai_foundation.store import SQLiteGuardStore

    path = tmp_path / "guard.db"
    store = SQLiteGuardStore(path)

    first = GuardCore(store.load(), store=store)
    assert OperatorActions(first).approve_run("durable-run").ok

    restarted = GuardCore(store.load(), store=store)

    assert "durable-run" in restarted.state.approvals

def test_operator_reconcile_uses_public_guard_boundary():
 class G:
  def reconcile_effect(self,e,p,port): assert e=='e'; return 'VERIFIED_COMPLETE'
 assert OperatorActions(G()).reconcile_effect('e',object(),object()).ok


def test_operator_cancel_is_durable_across_guard_restart(tmp_path):
 from ai_foundation.store import SQLiteGuardStore
 path=tmp_path/'guard.db'; store=SQLiteGuardStore(path)
 first=GuardCore(store.load(),store=store); assert OperatorActions(first).cancel_run('durable-cancel').ok
 restarted=GuardCore(store.load(),store=store)
 assert 'durable-cancel' in restarted.state.cancellations
