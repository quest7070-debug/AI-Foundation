from ai_foundation.durable_work import *
def test_restart_skips_durably_verified_step(tmp_path):
 s=SQLiteWorkStore(tmp_path/'w.db'); n={'a':0}
 def a(): n['a']+=1; return 'ok'
 def boom(): raise RuntimeError('x')
 r=DurableWorkRunner(s); assert r.execute('j',[('a',a),('b',boom)]) is WorkStatus.FAILED
 r2=DurableWorkRunner(SQLiteWorkStore(tmp_path/'w.db'))
 assert r2.execute('j',[('a',a),('b',lambda:'ok')]) is WorkStatus.VERIFIED and n['a']==1
def test_waiting_human_is_durable_and_resume_does_not_repeat_prior(tmp_path):
 s=SQLiteWorkStore(tmp_path/'w.db'); seen=[]
 assert DurableWorkRunner(s).execute('j',[('read',lambda:seen.append('r') or 'ok'),('effect',lambda:'WAITING_HUMAN'),('after',lambda:seen.append('x') or 'ok')]) is WorkStatus.WAITING_HUMAN
 assert DurableWorkRunner(SQLiteWorkStore(tmp_path/'w.db')).execute('j',[('read',lambda:seen.append('bad') or 'ok'),('effect',lambda:'approved'),('after',lambda:seen.append('x') or 'ok')]) is WorkStatus.VERIFIED
 assert seen==['r','x']

def test_existing_database_migrates_updated_at_without_losing_work(tmp_path):
 import sqlite3
 p=tmp_path/'old.db'
 with sqlite3.connect(p) as d:d.execute("CREATE TABLE work_steps(job_id TEXT,position INTEGER,name TEXT,status TEXT,result TEXT,PRIMARY KEY(job_id,position))");d.execute("INSERT INTO work_steps VALUES('j',0,'x','PLANNED','')")
 s=SQLiteWorkStore(p);assert s.load('j')[0].name=='x'
 with sqlite3.connect(p) as d:assert 'updated_at' in {r[1] for r in d.execute('PRAGMA table_info(work_steps)')}


def test_retry_semantics_are_explicit_for_effect_safety():
 assert DurableWorkRunner.retry_safe(WorkStatus.PLANNED)
 assert DurableWorkRunner.retry_safe(WorkStatus.FAILED,effectful=False)
 assert not DurableWorkRunner.retry_safe(WorkStatus.FAILED,effectful=True,reconciled=False)
 assert DurableWorkRunner.retry_safe(WorkStatus.FAILED,effectful=True,reconciled=True)
 assert not DurableWorkRunner.retry_safe(WorkStatus.RUNNING)
 assert not DurableWorkRunner.retry_safe(WorkStatus.WAITING_HUMAN)


def test_uncertain_effect_result_never_becomes_verified_work(tmp_path):
 s=SQLiteWorkStore(tmp_path/'w.db')
 status=DurableWorkRunner(s).execute('j',[('effect',lambda:'UNCERTAIN_RECONCILE_REQUIRED')])
 assert status is WorkStatus.RUNNING
 assert s.load('j')[0].status is WorkStatus.RUNNING

def test_in_progress_effect_result_never_becomes_verified_work(tmp_path):
 s=SQLiteWorkStore(tmp_path/'w.db')
 status=DurableWorkRunner(s).execute('j',[('effect',lambda:'EFFECT_IN_PROGRESS')])
 assert status is WorkStatus.RUNNING
 assert s.load('j')[0].status is WorkStatus.RUNNING
