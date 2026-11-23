import sqlite3
from ai_foundation.retention import RetentionPolicy,RetentionService
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.durable_inference import SQLiteInferenceAttemptStore

def test_retention_prunes_only_safe_old_rows(tmp_path):
 now=2_000_000_000.; g=tmp_path/'g.db'; w=tmp_path/'w.db'; i=tmp_path/'i.db'
 SQLiteGuardStore(g); SQLiteWorkStore(w); SQLiteInferenceAttemptStore(i)
 with sqlite3.connect(g) as d:
  d.execute("INSERT INTO effect_claims VALUES('old','x',?)",(now-10*86400,)); d.execute("INSERT INTO effect_claims VALUES('live','x',?)",(now+10,))
 with sqlite3.connect(w) as d:
  d.execute("INSERT INTO work_steps(job_id,position,name,status,result,updated_at) VALUES('j',0,'x','VERIFIED','',?)",(now-100*86400,))
  d.execute("INSERT INTO human_inputs VALUES('j',0,'old',?,?,NULL)",(now-100*86400,now-40*86400))
  d.execute("INSERT INTO human_inputs VALUES('j',0,'pending',?,NULL,NULL)",(now-99*86400,))
 with sqlite3.connect(i) as d:
  d.execute("INSERT INTO inference_attempts VALUES('v','b','VERIFIED','x',?)",(now-100*86400,))
  d.execute("INSERT INTO inference_attempts VALUES('u','b','UNCERTAIN',NULL,?)",(now-100*86400,))
 out=RetentionService(g,w,i,RetentionPolicy(),lambda:now).prune()
 assert out['effect_claims']==1 and out['human_inputs']==1 and out['inference_attempts']==1
 with sqlite3.connect(g) as d: assert d.execute('select effect_id from effect_claims').fetchall()==[('live',)]
 with sqlite3.connect(w) as d:
  assert d.execute('select response from human_inputs').fetchall()==[('pending',)]
  assert d.execute('select count(*) from work_steps').fetchone()[0]==1
 with sqlite3.connect(i) as d: assert d.execute('select request_id,status from inference_attempts').fetchall()==[('u','UNCERTAIN')]

def test_retention_is_idempotent(tmp_path):
 now=2_000_000_000.; g=tmp_path/'g.db'; w=tmp_path/'w.db'; i=tmp_path/'i.db'
 SQLiteGuardStore(g); SQLiteWorkStore(w); SQLiteInferenceAttemptStore(i)
 svc=RetentionService(g,w,i,clock=lambda:now)
 assert svc.prune()=={'effect_claims':0,'target_claims':0,'startup_leases':0,'human_inputs':0,'inference_attempts':0}
 assert svc.prune()=={'effect_claims':0,'target_claims':0,'startup_leases':0,'human_inputs':0,'inference_attempts':0}


def test_retention_loop_is_daily_floor_and_suppresses_overlap(tmp_path):
 from ai_foundation.retention import RetentionLoop
 class S:
  def __init__(self):self.n=0
  def prune(self):self.n+=1;return {'n':self.n}
 x=S();loop=RetentionLoop(x,interval=1);assert loop.interval==3600
 assert loop.tick()=={'n':1} and loop._last=={'n':1}
 loop._lock.acquire()
 try:assert loop.tick() is None and x.n==1
 finally:loop._lock.release()
