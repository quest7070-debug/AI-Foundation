import sqlite3
import hashlib
from dataclasses import dataclass
import time
from .orchestration import WorkStatus
@dataclass(frozen=True)
class StoredStep:
 job_id:str; position:int; name:str; status:WorkStatus; result:str
class SQLiteWorkStore:
 def __init__(self,path):
  self.path=str(path)
  # Initialization/migration can be reached by multiple producer/operator processes.
  # Serialize schema inspection + ALTER exactly like the routing store.
  c=self._db()
  try:
   c.execute('BEGIN EXCLUSIVE')
   c.execute('CREATE TABLE IF NOT EXISTS work_steps(job_id TEXT, position INTEGER, name TEXT, status TEXT, result TEXT, PRIMARY KEY(job_id,position))')
   cols={r[1] for r in c.execute('PRAGMA table_info(work_steps)')}
   if 'updated_at' not in cols:c.execute('ALTER TABLE work_steps ADD COLUMN updated_at REAL NOT NULL DEFAULT 0')
   hcols={r[1] for r in c.execute('PRAGMA table_info(human_inputs)')} if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='human_inputs'").fetchone() else set()
   c.execute('CREATE TABLE IF NOT EXISTS human_inputs(job_id TEXT NOT NULL, position INTEGER NOT NULL, response TEXT NOT NULL, created_at REAL NOT NULL, consumed_at REAL, context_digest TEXT, PRIMARY KEY(job_id,position,created_at))')
   hcols={r[1] for r in c.execute('PRAGMA table_info(human_inputs)')}
   if 'context_digest' not in hcols:c.execute('ALTER TABLE human_inputs ADD COLUMN context_digest TEXT')
   c.execute('CREATE INDEX IF NOT EXISTS idx_work_steps_status_updated ON work_steps(status,updated_at DESC,job_id,position)')
   c.execute('CREATE INDEX IF NOT EXISTS idx_human_inputs_pending ON human_inputs(job_id,position,consumed_at,created_at)')
   c.execute('CREATE INDEX IF NOT EXISTS idx_human_inputs_consumed ON human_inputs(consumed_at)')
   c.commit()
  finally:c.close()
 def _db(self):
  c=sqlite3.connect(self.path,timeout=5); c.execute('PRAGMA busy_timeout=5000'); return c
 def request_development_review(self,job_id,contract):
  """Persist untrusted development intent; never create an executable intake."""
  with self._db() as c:
   c.execute('BEGIN IMMEDIATE')
   old=c.execute('SELECT name,status,result FROM work_steps WHERE job_id=? AND position=0',(job_id,)).fetchone()
   if old:
    if old[0]!='development-request' or old[2]!=contract:raise ValueError('DEVELOPMENT_REQUEST_CONFLICT')
    return True
   count=c.execute("SELECT COUNT(*) FROM work_steps WHERE name='development-request'").fetchone()[0]
   if count>=64:raise ValueError('DEVELOPMENT_REQUEST_REVIEW_CAPACITY')
   c.execute('INSERT INTO work_steps(job_id,position,name,status,result,updated_at) VALUES(?,?,?,?,?,unixepoch())',(job_id,0,'development-request',WorkStatus.WAITING_HUMAN.value,contract))
   return False
 def development_review_requests(self,prefix):
  with self._db() as c:
   rows=c.execute("SELECT job_id,result FROM work_steps WHERE name='development-request' AND substr(job_id,1,?)=? ORDER BY updated_at,job_id LIMIT 64",(len(prefix),prefix)).fetchall()
  return rows
 def cancel_development_review(self,job_id,expected_contract):
  """Withdraw one exact pending request, preserving its immutable payload."""
  import re
  if (type(job_id) is not str
      or re.fullmatch(r'mcp-development-request:[0-9a-f]{64}:[a-z0-9][a-z0-9-]{0,47}',job_id) is None
      or type(expected_contract) is not str or not expected_contract):
   raise ValueError('exact development request contract required')
  with self._db() as c:
   changed=c.execute(
    "UPDATE work_steps SET status=?,updated_at=unixepoch() "
    "WHERE job_id=? AND position=0 AND name='development-request' AND status=? AND result=?",
    (WorkStatus.CANCELLED.value,job_id,WorkStatus.WAITING_HUMAN.value,expected_contract))
   return changed.rowcount==1
 def create_intake(self,job_id,text,created_at):
  """Atomically create producer metadata and its initial durable work step in the shared work DB."""
  with self._db() as c:
   c.execute('BEGIN IMMEDIATE')
   c.execute('CREATE TABLE IF NOT EXISTS task_intake(job_id TEXT PRIMARY KEY, text TEXT NOT NULL, created_at INTEGER NOT NULL)')
   c.execute('INSERT INTO task_intake VALUES(?,?,?)',(job_id,text,created_at))
   c.execute('INSERT INTO work_steps(job_id,position,name,status,result,updated_at) VALUES(?,?,?,?,?,unixepoch())',(job_id,0,'intake',WorkStatus.PLANNED.value,''))
 def ensure(self,job_id,names):
  if len(names)!=len(set(names)): raise ValueError('duplicate work step name')
  with self._db() as c:
   existing=c.execute('SELECT position,name FROM work_steps WHERE job_id=? ORDER BY position',(job_id,)).fetchall()
   for pos,name in existing:
    if pos >= len(names) or names[pos] != name: raise ValueError('work plan changed for existing job')
   for i,n in enumerate(names): c.execute('INSERT OR IGNORE INTO work_steps(job_id,position,name,status,result,updated_at) VALUES(?,?,?,?,?,unixepoch())',(job_id,i,n,WorkStatus.PLANNED.value,''))
 def load(self,job_id):
  with self._db() as c: rows=c.execute('SELECT job_id,position,name,status,result FROM work_steps WHERE job_id=? ORDER BY position',(job_id,)).fetchall()
  return [StoredStep(a,b,c,WorkStatus(d),e) for a,b,c,d,e in rows]
 def load_many(self,job_ids):
  """Load a bounded caller-supplied job window in one query; never scan work history."""
  ids=tuple(dict.fromkeys(job_ids))
  if not ids:return {}
  if len(ids)>100:raise ValueError('job window too large')
  marks=','.join('?' for _ in ids)
  with self._db() as c: rows=c.execute(f'SELECT job_id,position,name,status,result FROM work_steps WHERE job_id IN ({marks}) ORDER BY job_id,position',ids).fetchall()
  out={x:[] for x in ids}
  for a,b,c,d,e in rows:out[a].append(StoredStep(a,b,c,WorkStatus(d),e))
  return out
 def claim_not_running(self,job_id,pos):
  with self._db() as c:
   cur=c.execute('UPDATE work_steps SET status=?,updated_at=unixepoch() WHERE job_id=? AND position=? AND status IN (?,?,?)',(WorkStatus.RUNNING.value,job_id,pos,WorkStatus.PLANNED.value,WorkStatus.FAILED.value,WorkStatus.WAITING_HUMAN.value))
   return cur.rowcount==1
 def set(self,job_id,pos,status,result=''):
  with self._db() as c: c.execute('UPDATE work_steps SET status=?,result=?,updated_at=unixepoch() WHERE job_id=? AND position=?',(status.value,result,job_id,pos))
 def transition(self,job_id,pos,expected,status,result=''):
  """Compare-and-set status; a late worker cannot overwrite cancellation or completion."""
  from_states=(expected,) if isinstance(expected,WorkStatus) else tuple(expected)
  if not from_states or any(not isinstance(x,WorkStatus) for x in from_states):
   raise ValueError('expected work states required')
  marks=','.join('?' for _ in from_states)
  with self._db() as c:
   cur=c.execute(f'UPDATE work_steps SET status=?,result=?,updated_at=unixepoch() WHERE job_id=? AND position=? AND status IN ({marks})',
                 (status.value,result,job_id,pos,*(x.value for x in from_states)))
   return cur.rowcount==1
 def human_context_digest(self,job_id,pos):
  with self._db() as c:
   row=c.execute('SELECT name,status,result FROM work_steps WHERE job_id=? AND position=?',(job_id,pos)).fetchone()
   intake=c.execute('SELECT text FROM task_intake WHERE job_id=?',(job_id,)).fetchone() if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_intake'").fetchone() else None
  if row is None: raise KeyError((job_id,pos))
  raw='|'.join((job_id,str(pos),row[0],row[2],intake[0] if intake else ''))
  return hashlib.sha256(raw.encode()).hexdigest()
 def submit_human_input(self,job_id,pos,response,context_digest=None):
  response=' '.join((response or '').split())
  if not response or len(response)>4000: raise ValueError('invalid human input')
  with self._db() as c:
   row=c.execute('SELECT status FROM work_steps WHERE job_id=? AND position=?',(job_id,pos)).fetchone()
   if row is None: raise KeyError((job_id,pos))
   if row[0] != WorkStatus.WAITING_HUMAN.value: raise ValueError('work is not waiting for human input')
   digest=context_digest or self.human_context_digest(job_id,pos)
   c.execute('INSERT INTO human_inputs(job_id,position,response,created_at,consumed_at,context_digest) VALUES(?,?,?,?,NULL,?)',(job_id,pos,response,time.time(),digest))
  return True
 def pending_human_input_record(self,job_id,pos):
  with self._db() as c: row=c.execute('SELECT response,context_digest FROM human_inputs WHERE job_id=? AND position=? AND consumed_at IS NULL ORDER BY created_at LIMIT 1',(job_id,pos)).fetchone()
  return row
 def pending_human_input(self,job_id,pos):
  row=self.pending_human_input_record(job_id,pos); return row[0] if row else None
 def human_input_context_valid(self,job_id,pos):
  row=self.pending_human_input_record(job_id,pos)
  if not row or not row[1]: return False
  return row[1]==self.human_context_digest(job_id,pos)
 def consume_human_input(self,job_id,pos):
  with self._db() as c:
   row=c.execute('SELECT rowid,response FROM human_inputs WHERE job_id=? AND position=? AND consumed_at IS NULL ORDER BY created_at LIMIT 1',(job_id,pos)).fetchone()
   if not row:return None
   c.execute('UPDATE human_inputs SET consumed_at=? WHERE rowid=? AND consumed_at IS NULL',(time.time(),row[0]))
   return row[1]
 def resolve_running(self,job_id,pos,result):
  with self._db() as c:
   cur=c.execute('UPDATE work_steps SET status=?,result=?,updated_at=unixepoch() WHERE job_id=? AND position=? AND status=?',(WorkStatus.VERIFIED.value,result,job_id,pos,WorkStatus.RUNNING.value))
   return cur.rowcount==1
class DurableWorkRunner:
 def __init__(self,store): self.store=store
 @staticmethod
 def retry_safe(status,effectful=False,reconciled=False):
  if status is WorkStatus.PLANNED: return True
  if status is WorkStatus.FAILED: return not effectful or reconciled
  return False
 def reconcile_running(self,job_id,position,reconcile):
  saved=self.store.load(job_id)[position]
  if saved.status is not WorkStatus.RUNNING: return saved.status
  result=reconcile()
  if result == "VERIFIED_COMPLETE":
   if not self.store.resolve_running(job_id,position,result): return WorkStatus.RUNNING
   return WorkStatus.VERIFIED
  return WorkStatus.RUNNING
 def execute(self,job_id,steps):
  self.store.ensure(job_id,[n for n,_ in steps])
  for saved,(name,fn) in zip(self.store.load(job_id),steps):
   if saved.status is WorkStatus.VERIFIED: continue
   if saved.status is WorkStatus.RUNNING: return WorkStatus.RUNNING
   if saved.status is WorkStatus.FAILED and not self.retry_safe(saved.status): return WorkStatus.FAILED
   if not self.store.claim_not_running(job_id,saved.position): return WorkStatus.RUNNING
   try: result=fn()
   except PermissionError as e:
    if not self.store.transition(job_id,saved.position,WorkStatus.RUNNING,WorkStatus.WAITING_HUMAN,str(e)): return WorkStatus.RUNNING
    return WorkStatus.WAITING_HUMAN
   except Exception as e:
    # Durable/user-visible state must not persist arbitrary exception text: provider,
    # tool, or SDK exceptions may embed credentials, URLs, or request content.
    if not self.store.transition(job_id,saved.position,WorkStatus.RUNNING,WorkStatus.FAILED,type(e).__name__): return WorkStatus.RUNNING
    return WorkStatus.FAILED
   if result in {'WAITING_HUMAN','WAITING_HUMAN_UNCERTAIN_EFFECT'}:
    if not self.store.transition(job_id,saved.position,WorkStatus.RUNNING,WorkStatus.WAITING_HUMAN,result): return WorkStatus.RUNNING
    return WorkStatus.WAITING_HUMAN
   # Durable work state is orchestration state, not proof of an external effect.
   # Effectful steps must return Guard's independently verified terminal result;
   # arbitrary success-like strings cannot promote a step to VERIFIED.
   if result in {'UNCERTAIN_RECONCILE_REQUIRED','CANCELLED_RECONCILE_REQUIRED','EFFECT_IN_PROGRESS','TARGET_IN_PROGRESS'}:
    return WorkStatus.RUNNING
   # Only Guard's independently verified terminal outcome may complete an effect.
   # Observational steps may still return arbitrary non-status text.
   if result in {'FAILED_VERIFICATION','FAILED_EFFECT','DENY','LOCAL_ONLY',
                 'EFFECT_STATE_CONFLICT','TARGET_PRECONDITION_CONFLICT'}:
    if not self.store.transition(job_id,saved.position,WorkStatus.RUNNING,WorkStatus.FAILED,result): return WorkStatus.RUNNING
    return WorkStatus.FAILED
   if not self.store.transition(job_id,saved.position,WorkStatus.RUNNING,WorkStatus.VERIFIED,str(result)):
    return WorkStatus.RUNNING
  return WorkStatus.VERIFIED

