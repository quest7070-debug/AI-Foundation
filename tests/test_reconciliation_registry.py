from ai_foundation.reconciliation_registry import SQLiteReconciliationRegistry,ReconciliationService
from ai_foundation.core import TaskPlan
class A:
 def reconcile_effect(self,e,p,port):
  assert p.target=='target' and port=='PORT'
  class R:ok=True;status='VERIFIED_COMPLETE'
  return R()
def test_recipe_survives_restart_and_resolves_port_by_binding(tmp_path):
 p=tmp_path/'r.sqlite';r=SQLiteReconciliationRegistry(p);r.register('e',TaskPlan('run','send','target',effect_id='e'),'tool:mail');r2=SQLiteReconciliationRegistry(p);x=ReconciliationService(A(),r2,{'tool:mail':'PORT'}).reconcile('e');assert x['ok'] and x['status']=='VERIFIED_COMPLETE'
def test_missing_recipe_and_port_fail_closed(tmp_path):
 r=SQLiteReconciliationRegistry(tmp_path/'r.sqlite');s=ReconciliationService(A(),r,{})
 assert s.reconcile('none')['status']=='RECIPE_NOT_FOUND';r.register('e',TaskPlan('r','a','t'),'missing');assert s.reconcile('e')['status']=='VERIFICATION_PORT_UNAVAILABLE'
def test_gateway_registers_recipe_before_effect(tmp_path):
 from ai_foundation.agent_tools import GuardedToolGateway
 from ai_foundation.core import CanonContract,GuardState
 from ai_foundation.guard import GuardCore
 class Port:
  def execute(self,p):pass
  def observe(self,p):return 'v'
 r=SQLiteReconciliationRegistry(tmp_path/'r.sqlite');g=GuardedToolGateway(GuardCore(GuardState()),CanonContract('x','c'),Port(),r,'tool:test');assert g.write(run_id='r',target='t',content='v',canon_revision='c')=='VERIFIED_COMPLETE';plan,b=r.load('r');assert plan.target=='t' and b=='tool:test'

def test_capability_is_effect_specific_and_requires_observe_port(tmp_path):
 r=SQLiteReconciliationRegistry(tmp_path/'r.sqlite');r.register('e',TaskPlan('run','send','target',effect_id='e'),'tool:mail')
 s=ReconciliationService(A(),r,{})
 assert s.capability('e')=='VERIFICATION_PORT_UNAVAILABLE' and not s.can_reconcile('e')
 assert s.capability('missing')=='RECIPE_NOT_FOUND'
 assert ReconciliationService(A(),r,{'tool:mail':'PORT'}).can_reconcile('e')
