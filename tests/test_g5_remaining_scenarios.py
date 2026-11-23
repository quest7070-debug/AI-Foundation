from ai_foundation.core import *
from ai_foundation.guard import GuardCore
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.coordinator import ExecutionCoordinator
from ai_foundation.durable_work import SQLiteWorkStore,DurableWorkRunner
from ai_foundation.orchestration import WorkStatus
class Port:
 def __init__(self):self.execs=0;self.obs=0;self.v=''
 def execute(self,p):self.execs+=1;self.v=p.text
 def observe(self,p):self.obs+=1;return self.v
def test_waiting_human_restart_authorize_and_deny_are_durable(tmp_path):
 db=tmp_path/'g.db';store=SQLiteGuardStore(db);p=TaskPlan('r','send_email','t',text='x',canon_revision='c');canon=CanonContract('repo','c');port=Port();g=GuardCore(store.load(),store=store)
 assert g.execute(p,canon,port,'x')=='WAITING_HUMAN' and port.execs==0
 from ai_foundation.store import approval_request_ref
 resumed_store=SQLiteGuardStore(db)
 with resumed_store._connect() as conn:
  action,target,nonce,revision,effect=conn.execute(
   'SELECT action,target,request_nonce,canon_revision,effect_id FROM approval_requests WHERE run_id=?',('r',)).fetchone()
 assert GuardCore(resumed_store.load(),store=resumed_store).approve_pending(
  'r',approval_request_ref('r',action,target,nonce,revision,effect))
 restarted=GuardCore(SQLiteGuardStore(db).load(),store=SQLiteGuardStore(db));assert restarted.execute(p,canon,port,'x')=='VERIFIED_COMPLETE' and port.execs==1
 p2=TaskPlan('r2','send_email','t2',text='y',canon_revision='c');GuardCore(SQLiteGuardStore(db).load(),store=SQLiteGuardStore(db)).cancel('r2');assert GuardCore(SQLiteGuardStore(db).load(),store=SQLiteGuardStore(db)).execute(p2,canon,port,'y')=='DENY' and port.execs==1
def test_local_only_never_touches_cloud(tmp_path):
 cloud=Port();local=Port();store=SQLiteGuardStore(tmp_path/'g.db');g=GuardCore(store.load(),store=store);c=ExecutionCoordinator(g,cloud,local);p=TaskPlan('private','compute','local',text='password=supersecret',canon_revision='c')
 assert c.run(p,CanonContract('r','c'),'password=supersecret')=='LOCAL_VERIFIED_COMPLETE';assert cloud.execs==0 and cloud.obs==0 and local.execs==1
def test_failed_work_restart_recovers_without_repeating_verified_step(tmp_path):
 db=tmp_path/'w.db';seen=[]
 def first():seen.append('first');return 'ok'
 def fail():raise RuntimeError('temporary')
 assert DurableWorkRunner(SQLiteWorkStore(db)).execute('j',[('first',first),('second',fail)]) is WorkStatus.FAILED
 assert DurableWorkRunner(SQLiteWorkStore(db)).execute('j',[('first',first),('second',lambda:seen.append('recovered') or 'ok')]) is WorkStatus.VERIFIED
 assert seen==['first','recovered']
