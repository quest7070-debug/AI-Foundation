import sqlite3
from ai_foundation.core import TaskPlan,CanonContract,EffectStatus,EffectIntent,GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.store import SQLiteGuardStore

class Port:
 def __init__(self,fail=None):self.fail=fail;self.execs=0;self.value=''
 def execute(self,p):
  self.execs+=1
  if self.fail=='before-effect':raise RuntimeError('before')
  self.value=p.text
  if self.fail=='after-effect':raise RuntimeError('lost response')
 def observe(self,p):
  if self.fail=='readback':return 'mismatch'
  return self.value

def plan():return TaskPlan('r','write','target',text='DONE',canon_revision='c1',exclusive_target=True,effect_id='e')

def test_fault_boundary_before_effect_requires_reconciliation_and_never_blind_reexec(tmp_path):
 s=SQLiteGuardStore(tmp_path/'g.db');p=Port('before-effect');g=GuardCore(s.load(),100,s)
 assert g.execute(plan(),CanonContract('repo','c1'),p,'DONE')=='UNCERTAIN_RECONCILE_REQUIRED'
 assert s.get_effect('e').status is EffectStatus.UNCERTAIN
 p.fail=None;g2=GuardCore(s.load(),100,s);assert g2.execute(plan(),CanonContract('repo','c1'),p,'DONE')=='WAITING_HUMAN_UNCERTAIN_EFFECT';assert p.execs==1

def test_fault_boundary_after_effect_reconciles_observe_only_once(tmp_path):
 s=SQLiteGuardStore(tmp_path/'g.db');p=Port('after-effect');g=GuardCore(s.load(),100,s)
 assert g.execute(plan(),CanonContract('repo','c1'),p,'DONE')=='UNCERTAIN_RECONCILE_REQUIRED';assert p.execs==1
 p.fail=None;g2=GuardCore(s.load(),100,s);assert g2.execute(plan(),CanonContract('repo','c1'),p,'DONE')=='VERIFIED_COMPLETE';assert p.execs==1
 assert s.get_effect('e').status is EffectStatus.VERIFIED

def test_fault_boundary_readback_persists_failed_and_never_reexecutes(tmp_path):
 s=SQLiteGuardStore(tmp_path/'g.db');p=Port('readback');g=GuardCore(s.load(),100,s)
 assert g.execute(plan(),CanonContract('repo','c1'),p,'DONE')=='FAILED_VERIFICATION';assert p.execs==1
 p.fail=None;assert GuardCore(s.load(),100,s).execute(plan(),CanonContract('repo','c1'),p,'DONE')=='FAILED_EFFECT';assert p.execs==1

def test_crash_like_persisted_executing_state_is_not_blindly_dispatched(tmp_path):
 s=SQLiteGuardStore(tmp_path/'g.db');p=Port();g=GuardCore(s.load(),100,s)
 # Persist the exact pre-dispatch durable boundary, then simulate process death before port.execute.
 st=s.load();st.effects['e']=EffectIntent('e','r','target','DONE',EffectStatus.PLANNED);s.save(st);assert s.transition_effect('e',EffectStatus.PLANNED,EffectStatus.AUTHORIZED);assert s.transition_effect('e',EffectStatus.AUTHORIZED,EffectStatus.EXECUTING)
 restarted=GuardCore(s.load(),100,s);assert restarted.execute(plan(),CanonContract('repo','c1'),p,'DONE')=='WAITING_HUMAN_UNCERTAIN_EFFECT';assert p.execs==0
 assert s.get_effect('e').status is EffectStatus.UNCERTAIN
