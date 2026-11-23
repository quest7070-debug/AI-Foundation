from pathlib import Path
from ai_foundation.cedar import CedarPolicyBoundary
from ai_foundation.core import Decision, TaskPlan
ROOT=Path(__file__).parents[1]
CEDAR=ROOT/'.tools/cedar/cedar-policy-cli-aarch64-apple-darwin/cedar'

def boundary(principal='User::"local-owner"'):
    return CedarPolicyBoundary(CEDAR,ROOT/'policy/default.cedar',ROOT/'policy/schema.cedarschema',ROOT/'policy/entities.json',principal)

def test_real_cedar_allows_owner_write():
    assert boundary().authorize(TaskPlan('r','write','repo',canon_revision='c1')) is Decision.ALLOW

def test_real_cedar_default_denies_unknown_principal():
    assert boundary('User::"other"').authorize(TaskPlan('r','write','repo',canon_revision='c1')) is Decision.DENY

def test_real_cedar_denies_unknown_action_by_schema_validation():
    assert boundary().authorize(TaskPlan('r','unknown','repo',canon_revision='c1')) is Decision.DENY

def test_real_cedar_guard_effect_e2e(tmp_path):
    from ai_foundation.guard import GuardCore
    from ai_foundation.store import SQLiteGuardStore
    from ai_foundation.core import CanonContract, GuardState
    class Port:
        def __init__(self): self.state={}; self.execute_count=0
        def execute(self,p): self.execute_count+=1; self.state[p.target]=p.text
        def observe(self,p): return self.state.get(p.target,'')
    store=SQLiteGuardStore(tmp_path/'guard.db'); port=Port()
    p=TaskPlan('cedar-e2e','write','repo',text='ok',canon_revision='c1')
    result=GuardCore(store.load(),100,store,policy_boundary=boundary()).execute(p,CanonContract('repo','c1'),port,'ok')
    assert result == 'VERIFIED_COMPLETE'
    assert port.execute_count == 1
    assert port.state['repo'] == 'ok'
    assert store.load().effects['cedar-e2e'].status.value == 'VERIFIED'

def test_real_cedar_guard_denial_e2e_has_no_effect(tmp_path):
    from ai_foundation.guard import GuardCore
    from ai_foundation.store import SQLiteGuardStore
    from ai_foundation.core import CanonContract
    class Port:
        execute_count=0
        def execute(self,p): self.execute_count+=1
        def observe(self,p): return ''
    store=SQLiteGuardStore(tmp_path/'guard.db'); port=Port()
    p=TaskPlan('cedar-deny','write','repo',text='ok',canon_revision='c1')
    result=GuardCore(store.load(),100,store,policy_boundary=boundary('User::"other"')).execute(p,CanonContract('repo','c1'),port,'ok')
    assert result == 'DENY'
    assert port.execute_count == 0
    assert 'cedar-deny' not in store.load().effects

def test_real_cedar_guard_denied_principal_has_no_effect(tmp_path):
    from ai_foundation.guard import GuardCore
    from ai_foundation.store import SQLiteGuardStore
    from ai_foundation.core import CanonContract
    class Port:
        execute_count=0
        def execute(self,p): self.execute_count+=1
        def observe(self,p): return ''
    store=SQLiteGuardStore(tmp_path/'guard.db'); port=Port()
    p=TaskPlan('cedar-deny','write','repo',text='ok',canon_revision='c1')
    g=GuardCore(store.load(),100,store,policy_boundary=boundary('User::"other"'))
    assert g.execute(p,CanonContract('repo','c1'),port,'ok') == 'DENY'
    assert port.execute_count == 0
    assert not store.load().effects
