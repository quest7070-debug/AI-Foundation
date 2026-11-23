from pathlib import Path
from ai_foundation.cedar import CedarPolicyBoundary
from ai_foundation.core import CanonContract, GuardState, TaskPlan
from ai_foundation.guard import GuardCore
from ai_foundation.store import SQLiteGuardStore

ROOT=Path(__file__).parents[1]
CEDAR=ROOT/'.tools/cedar/cedar-policy-cli-aarch64-apple-darwin/cedar'

class RealEffect:
    def __init__(self,path): self.path=path; self.execute_count=0
    def execute(self,plan):
        self.execute_count += 1
        self.path.write_text(plan.text)
    def observe(self,plan):
        return self.path.read_text() if self.path.exists() else ''

def cedar(principal='User::"local-owner"'):
    return CedarPolicyBoundary(CEDAR,ROOT/'policy/default.cedar',ROOT/'policy/schema.cedarschema',ROOT/'policy/entities.json',principal)

def test_cedar_guard_real_effect_e2e(tmp_path):
    store=SQLiteGuardStore(tmp_path/'guard.db'); target=tmp_path/'effect.txt'; port=RealEffect(target)
    p=TaskPlan('cedar-e2e','write',str(target),text='verified',canon_revision='c1')
    g=GuardCore(store.load(),100,store,policy_boundary=cedar())
    assert g.execute(p,CanonContract('repo','c1'),port,'verified') == 'VERIFIED_COMPLETE'
    assert target.read_text() == 'verified'
    assert port.execute_count == 1
    assert store.load().effects['cedar-e2e'].status.value == 'VERIFIED'

def test_cedar_guard_denied_principal_has_no_real_effect(tmp_path):
    store=SQLiteGuardStore(tmp_path/'guard.db'); target=tmp_path/'denied.txt'; port=RealEffect(target)
    p=TaskPlan('cedar-deny','write',str(target),text='must-not-exist',canon_revision='c1')
    g=GuardCore(store.load(),100,store,policy_boundary=cedar('User::"other"'))
    assert g.execute(p,CanonContract('repo','c1'),port,'must-not-exist') == 'DENY'
    assert not target.exists()
    assert port.execute_count == 0

def test_cedar_policy_change_before_effect_blocks_real_effect(tmp_path):
    store=SQLiteGuardStore(tmp_path/'guard.db'); target=tmp_path/'changed.txt'; port=RealEffect(target)
    policy=tmp_path/'dynamic.cedar'; policy.write_text((ROOT/'policy/default.cedar').read_text())
    boundary=CedarPolicyBoundary(CEDAR,policy,ROOT/'policy/schema.cedarschema',ROOT/'policy/entities.json')
    class ChangeAfterFirst:
        calls=0
        def authorize(self,p):
            self.calls += 1
            decision=boundary.authorize(p)
            if self.calls == 1: policy.write_text('')
            return decision
    p=TaskPlan('cedar-change','write',str(target),text='must-not-exist',canon_revision='c1')
    g=GuardCore(store.load(),100,store,policy_boundary=ChangeAfterFirst())
    assert g.execute(p,CanonContract('repo','c1'),port,'must-not-exist') == 'DENY'
    assert not target.exists()
    assert port.execute_count == 0
