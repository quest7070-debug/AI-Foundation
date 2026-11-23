import os, sqlite3, subprocess, sys
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.durable_inference import SQLiteInferenceAttemptStore

def _check(path):
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]

def test_repeated_sqlite_churn_checkpoint_and_reopen_stays_integral(tmp_path):
    g=tmp_path/'g.db'; w=tmp_path/'w.db'; i=tmp_path/'i.db'
    SQLiteGuardStore(g); SQLiteWorkStore(w); SQLiteInferenceAttemptStore(i)
    for cycle in range(12):
      with sqlite3.connect(g) as db:
        base=cycle*2000
        db.executemany('INSERT OR REPLACE INTO effects(effect_id,run_id,target,expected,status,paid_cost,updated_at) VALUES(?,?,?,?,?,?,?)',((f'e{x}',f'r{x}','t','x','FAILED' if x%3 else 'VERIFIED',0,x) for x in range(base,base+2000)))
        db.execute('DELETE FROM effects WHERE updated_at<?',(max(0,base-4000),)); db.commit(); db.execute('PRAGMA wal_checkpoint(PASSIVE)')
      with sqlite3.connect(w) as db:
        base=cycle*2000
        db.executemany('INSERT OR REPLACE INTO work_steps(job_id,position,name,status,result,updated_at) VALUES(?,?,?,?,?,?)',((f'j{x}',0,'n','FAILED' if x%3 else 'VERIFIED','',x) for x in range(base,base+2000)))
        db.execute('DELETE FROM work_steps WHERE updated_at<?',(max(0,base-4000),)); db.commit(); db.execute('PRAGMA wal_checkpoint(PASSIVE)')
      with sqlite3.connect(i) as db:
        base=cycle*2000
        db.executemany('INSERT OR REPLACE INTO inference_attempts VALUES(?,?,?,?,?)',((f'q{x}','b','FAILED','',x) for x in range(base,base+2000)))
        db.execute('DELETE FROM inference_attempts WHERE updated_at<?',(max(0,base-4000),)); db.commit(); db.execute('PRAGMA wal_checkpoint(PASSIVE)')
      for p in (g,w,i):_check(p)
    # Reconstruct stores after churn and verify retained primary keys are unique.
    SQLiteGuardStore(g); SQLiteWorkStore(w); SQLiteInferenceAttemptStore(i)
    for p,table,key in ((g,'effects','effect_id'),(w,'work_steps','job_id || ":" || position'),(i,'inference_attempts','request_id')):
      _check(p)
      with sqlite3.connect(p) as db:
        total,unique=db.execute(f'SELECT COUNT(*),COUNT(DISTINCT {key}) FROM {table}').fetchone(); assert total==unique

def test_abrupt_writer_process_does_not_corrupt_committed_sqlite_state(tmp_path):
    p=tmp_path/'crash.db'; SQLiteGuardStore(p)
    code='''import os,sqlite3,sys\np=sys.argv[1]\ndb=sqlite3.connect(p);db.execute("PRAGMA journal_mode=WAL");db.execute("BEGIN IMMEDIATE");db.execute("INSERT INTO approvals(run_id) VALUES (?)",("uncommitted",));os._exit(23)'''
    r=subprocess.run([sys.executable,'-c',code,str(p)],check=False); assert r.returncode==23
    _check(p)
    with sqlite3.connect(p) as db: assert db.execute("SELECT COUNT(*) FROM approvals WHERE run_id='uncommitted'").fetchone()[0]==0
    # Recovery is writable and does not produce a ghost/duplicate authority row.
    with sqlite3.connect(p) as db: db.execute("INSERT INTO approvals(run_id) VALUES ('after-crash')")
    _check(p)
