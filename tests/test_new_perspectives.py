import os
import sqlite3
import threading
import pytest
from ai_foundation.core import CanonContract, GuardState, TaskPlan
from ai_foundation.durable_work import DurableWorkRunner, SQLiteWorkStore
from ai_foundation.guard import GuardCore
from ai_foundation.observability import JsonlTraceSink, Tracer, read_jsonl_trace
from ai_foundation.run_report import build_run_report
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.toolhive import ToolHiveFilesystemPort

class Port:
    def __init__(self): self.v=''; self.n=0
    def execute(self,p): self.n+=1; self.v=p.text
    def observe(self,p): return self.v

def test_unicode_identity_and_payload_roundtrip(tmp_path):
    store=SQLiteGuardStore(tmp_path/'g.db'); p=Port(); plan=TaskPlan('実行-🚀','write','対象/日本語',text='改行\n絵文字🔐\u0000終端',canon_revision='版-一',effect_id='効果-一')
    assert GuardCore(store.load(),100,store).execute(plan,CanonContract('正本','版-一'),p,plan.text)=='VERIFIED_COMPLETE'
    assert p.v==plan.text and store.load().effects['効果-一'].target=='対象/日本語'

def test_observability_sink_failure_does_not_hide_business_success(tmp_path):
    class BrokenSink:
        def emit(self,event): raise OSError('disk full')
    p=Port(); plan=TaskPlan('r','write','x',text='ok',canon_revision='c')
    with pytest.raises(OSError,match='disk full'):
        with Tracer(BrokenSink()).span('outer'):
            assert GuardCore(GuardState()).execute(plan,CanonContract('x','c'),p,'ok')=='VERIFIED_COMPLETE'
    assert p.n==1 and p.v=='ok'

def test_trace_append_is_parseable_under_concurrent_threads(tmp_path):
    path=tmp_path/'trace.jsonl'; sink=JsonlTraceSink(path); errors=[]
    def worker(i):
        try:
            with Tracer(sink).span('thread',{'run_id':i}): pass
        except Exception as e: errors.append(e)
    threads=[threading.Thread(target=worker,args=(i,)) for i in range(40)]
    [t.start() for t in threads]; [t.join() for t in threads]
    events=read_jsonl_trace(path)
    assert not errors and len(events)==40 and len({e.span_id for e in events})==40

def test_sqlite_database_corruption_is_not_silently_reset(tmp_path):
    path=tmp_path/'bad.db'; path.write_bytes(b'not-a-sqlite-database')
    with pytest.raises(sqlite3.DatabaseError): SQLiteGuardStore(path)

def test_work_plan_unicode_and_very_long_step_name(tmp_path):
    store=SQLiteWorkStore(tmp_path/'w.db'); runner=DurableWorkRunner(store); name='解析🔎'+('長'*5000)
    assert runner.execute('仕事-日本語',[(name,lambda:'完了')]).value=='VERIFIED'
    saved=store.load('仕事-日本語')[0]
    assert saved.name==name and saved.result=='完了'

def test_report_empty_trace_is_explicit_not_false_success():
    report=build_run_report(())
    assert report.trace_id=='' and report.span_count==0 and not report.passed
