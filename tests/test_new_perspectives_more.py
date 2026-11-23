import os
import pytest
from ai_foundation.core import CanonContract, GuardState, TaskPlan
from ai_foundation.guard import GuardCore
from ai_foundation.observability import JsonlTraceSink, Tracer
from ai_foundation.run_report import build_run_report
from ai_foundation.store import SQLiteGuardStore

class Port:
    def __init__(self): self.n=0; self.v=''
    def execute(self,p): self.n+=1; self.v=p.text
    def observe(self,p): return self.v

def test_negative_paid_cost_cannot_create_budget_credit(tmp_path):
    store=SQLiteGuardStore(tmp_path/'g.db'); p=Port(); plan=TaskPlan('neg','write','x',text='ok',paid_cost=-50,canon_revision='c')
    result=GuardCore(store.load(),10,store).execute(plan,CanonContract('x','c'),p,'ok')
    assert store.load().spent >= 0, result

def test_trace_sink_rejects_directory_target(tmp_path):
    sink=JsonlTraceSink(tmp_path)
    with pytest.raises(OSError):
        with Tracer(sink).span('x'): pass

def test_empty_report_must_not_be_passed():
    assert not build_run_report(()).passed

def test_empty_effect_id_does_not_alias_distinct_runs(tmp_path):
    store=SQLiteGuardStore(tmp_path/'g.db'); p=Port(); canon=CanonContract('x','c')
    a=TaskPlan('run-a','write','x',text='a',canon_revision='c')
    b=TaskPlan('run-b','write','x',text='b',canon_revision='c')
    assert GuardCore(store.load(),100,store).execute(a,canon,p,'a')=='VERIFIED_COMPLETE'
    assert GuardCore(store.load(),100,store).execute(b,canon,p,'b')=='VERIFIED_COMPLETE'
    assert p.n==2 and p.v=='b'
