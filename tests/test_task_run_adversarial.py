import threading,time
from ai_foundation.task_intake import TaskIntake
class O:
 status='VERIFIED_COMPLETE';result='ok'
def test_concurrent_task_run_executes_inference_once(tmp_path):
 x=TaskIntake(tmp_path/'w.db');r=x.submit('x');gate=threading.Event();calls=[]
 def run(_):calls.append(1);gate.wait(1);return O()
 out=[]
 a=threading.Thread(target=lambda:out.append(x.execute(r.job_id,run)));b=threading.Thread(target=lambda:out.append(x.execute(r.job_id,run)))
 a.start();time.sleep(.03);b.start();time.sleep(.03);gate.set();a.join();b.join();assert len(calls)==1;assert 'ok' in out and 'RUNNING' in out

def test_failed_outcome_is_durable_failed_not_success(tmp_path):
 x=TaskIntake(tmp_path/'w.db');r=x.submit('x');bad=type('O',(),{'status':'NO_ELIGIBLE_COMPUTE','result':None})()
 assert x.execute(r.job_id,lambda _:bad)=='NO_ELIGIBLE_COMPUTE';assert x.store.load(r.job_id)[0].status.value=='FAILED'

def test_concurrent_submits_never_split_metadata_from_work(tmp_path):
 import sqlite3
 x=TaskIntake(tmp_path/'w.db');out=[]
 ts=[threading.Thread(target=lambda i=i:out.append(x.submit(f'job {i}').job_id)) for i in range(20)];[t.start() for t in ts];[t.join() for t in ts]
 with sqlite3.connect(tmp_path/'w.db') as d:
  meta={r[0] for r in d.execute('select job_id from task_intake')};work={r[0] for r in d.execute('select distinct job_id from work_steps')}
 assert len(out)==20 and meta==work==set(out)


def _open_store(path,q):
 try:
  from ai_foundation.durable_work import SQLiteWorkStore
  SQLiteWorkStore(path); q.put('ok')
 except Exception as e:q.put(type(e).__name__+':'+str(e))

def test_work_store_schema_initialization_is_cross_process_safe(tmp_path):
 import multiprocessing as mp
 path=str(tmp_path/'fresh.db');q=mp.Queue();ps=[mp.Process(target=_open_store,args=(path,q)) for _ in range(6)]
 [p.start() for p in ps];[p.join() for p in ps]
 assert [q.get() for _ in ps]==['ok']*6
