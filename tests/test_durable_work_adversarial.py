import pytest
from ai_foundation.durable_work import *
def test_changed_step_definition_does_not_silently_reuse_old_verified_state(tmp_path):
 s=SQLiteWorkStore(tmp_path/'w.db')
 assert DurableWorkRunner(s).execute('j',[('old',lambda:'ok')]) is WorkStatus.VERIFIED
 seen=[]
 with pytest.raises(ValueError,match='work plan changed'):
  DurableWorkRunner(SQLiteWorkStore(tmp_path/'w.db')).execute('j',[('new',lambda:seen.append(1) or 'ok')])
 assert seen==[]
def test_added_step_after_completed_job_executes(tmp_path):
 s=SQLiteWorkStore(tmp_path/'w.db'); seen=[]
 assert DurableWorkRunner(s).execute('j',[('a',lambda:'ok')]) is WorkStatus.VERIFIED
 assert DurableWorkRunner(s).execute('j',[('a',lambda:'bad'),('b',lambda:seen.append('b') or 'ok')]) is WorkStatus.VERIFIED
 assert seen==['b']

def test_removed_step_from_existing_job_fails_closed(tmp_path):
 s=SQLiteWorkStore(tmp_path/'w.db')
 assert DurableWorkRunner(s).execute('j',[('a',lambda:'ok'),('b',lambda:'ok')]) is WorkStatus.VERIFIED
 with pytest.raises(ValueError,match='work plan changed'):
  DurableWorkRunner(s).execute('j',[('a',lambda:'bad')])

def test_duplicate_step_names_fail_closed(tmp_path):
 s=SQLiteWorkStore(tmp_path/'w.db')
 with pytest.raises(ValueError):
  DurableWorkRunner(s).execute('j',[('same',lambda:'ok'),('same',lambda:'ok')])

def test_concurrent_runners_do_not_execute_same_step_twice(tmp_path):
 import threading,time
 path=tmp_path/'w.db'; count={'n':0}; lock=threading.Lock(); barrier=None
 def work():
  with lock: count['n']+=1
  time.sleep(.03)
  return 'ok'
 results=[]
 def go(): results.append(DurableWorkRunner(SQLiteWorkStore(path)).execute('j',[('a',work)]))
 ts=[threading.Thread(target=go) for _ in range(2)]
 [t.start() for t in ts]; [t.join() for t in ts]
 assert count['n']==1

def test_running_step_fails_closed_after_restart_until_reconciled(tmp_path):
 s=SQLiteWorkStore(tmp_path/'w.db'); s.ensure('j',['effect']); assert s.claim_not_running('j',0)
 seen=[]
 assert DurableWorkRunner(SQLiteWorkStore(tmp_path/'w.db')).execute('j',[('effect',lambda:seen.append(1) or 'ok')]) is WorkStatus.RUNNING
 assert seen==[]


def test_failure_state_does_not_persist_exception_secret(tmp_path):
 from ai_foundation.durable_work import SQLiteWorkStore,DurableWorkRunner
 from ai_foundation.orchestration import WorkStatus
 store=SQLiteWorkStore(tmp_path/'secret.db'); runner=DurableWorkRunner(store)
 def boom(): raise RuntimeError('sk-secret-value https://private.example/request')
 assert runner.execute('secret-job',[('call',boom)]) is WorkStatus.FAILED
 saved=store.load('secret-job')[0]
 assert saved.result=='RuntimeError'
 assert 'secret' not in saved.result and 'private.example' not in saved.result
