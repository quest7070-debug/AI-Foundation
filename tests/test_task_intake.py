from ai_foundation.task_intake import TaskIntake
from ai_foundation.orchestration import WorkStatus

def test_task_intake_creates_planned_durable_work(tmp_path):
    x=TaskIntake(tmp_path/'work.sqlite'); r=x.submit('  inspect   provider health  ')
    assert r.text=='inspect provider health'
    rows=x.store.load(r.job_id); assert len(rows)==1 and rows[0].name=='intake' and rows[0].status is WorkStatus.PLANNED
    assert x.recent()[0].job_id==r.job_id

def test_task_intake_rejects_empty_and_oversize(tmp_path):
    x=TaskIntake(tmp_path/'work.sqlite')
    for text in ('   ','x'*4001):
        try: x.submit(text); assert False
        except ValueError: pass

def test_submit_metadata_and_work_step_are_one_sqlite_transaction(tmp_path,monkeypatch):
 import sqlite3
 from ai_foundation.task_intake import TaskIntake
 t=TaskIntake(tmp_path/'w.db')
 # Force the second statement to fail inside the shared transaction; metadata must roll back too.
 original=t.store.create_intake
 def fail(job,text,created):
  with t.store._db() as c:
   c.execute('BEGIN IMMEDIATE');c.execute('INSERT INTO task_intake VALUES(?,?,?)',(job,text,created));raise RuntimeError('crash boundary')
 monkeypatch.setattr(t.store,'create_intake',fail)
 import pytest
 with pytest.raises(RuntimeError):t.submit('x')
 with sqlite3.connect(tmp_path/'w.db') as c:assert c.execute('select count(*) from task_intake').fetchone()[0]==0 and c.execute('select count(*) from work_steps').fetchone()[0]==0

def test_execute_addresses_exact_job_not_recent_window(tmp_path):
 x=TaskIntake(tmp_path/'w.db'); first=x.submit('first')
 for i in range(1001): x.submit(f'later {i}')
 outcome=type('O',(),{'status':'VERIFIED_COMPLETE','result':'ok','route_kind':'LOCAL','route_binding':'local:test'})()
 assert x.execute(first.job_id,lambda receipt: outcome)=='ok'
 assert x.store.load(first.job_id)[0].status is WorkStatus.VERIFIED


def test_cancel_active_intake_then_purge(tmp_path):
 i=TaskIntake(tmp_path/'w.db');r=i.submit('cleanup me')
 assert i.cancel(r.job_id) is True
 assert i.cancel(r.job_id) is False
 assert i.purge_terminal()==1
 assert i.recent()==[]
