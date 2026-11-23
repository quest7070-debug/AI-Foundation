from ai_foundation.core import CanonContract, GuardState, TaskPlan
from ai_foundation.durable_work import DurableWorkRunner, SQLiteWorkStore
from ai_foundation.guard import GuardCore
from ai_foundation.instrumentation import ObservedDurableWorkRunner, ObservedGuard, ObservedSpecialist
from ai_foundation.observability import InMemoryTraceSink, Tracer

class Port:
    def __init__(self): self.v=''
    def execute(self,p): self.v=p.text
    def observe(self,p): return self.v

def test_observed_guard_preserves_semantics_and_links_effect():
    sink=InMemoryTraceSink(); observed=ObservedGuard(GuardCore(GuardState()),Tracer(sink)); p=Port()
    plan=TaskPlan('r','write','repo',text='ok',canon_revision='c',effect_id='e')
    assert observed.execute(plan,CanonContract('x','c'),p,'ok')=='VERIFIED_COMPLETE'
    event=sink.events[0]
    assert event.name=='guard.execute' and event.evidence_ids==('effect:e',)
    assert event.attributes['run_id']=='r' and 'text' not in event.attributes

def test_observed_work_has_parent_child_spans(tmp_path):
    sink=InMemoryTraceSink(); runner=ObservedDurableWorkRunner(DurableWorkRunner(SQLiteWorkStore(tmp_path/'w.db')),Tracer(sink))
    assert runner.execute('j',[('research',lambda:'ok'),('effect',lambda:'ok')]).value=='VERIFIED'
    steps=[e for e in sink.events if e.name=='work.step']; root=[e for e in sink.events if e.name=='work.execute'][0]
    assert len(steps)==2 and all(e.trace_id==root.trace_id and e.parent_span_id==root.span_id for e in steps)

def test_observed_specialist_does_not_trace_payload():
    class S:
        def summarize(self,text): return 'done'
    sink=InMemoryTraceSink(); s=ObservedSpecialist(S(),Tracer(sink),'text-analysis')
    assert s.call('summarize','PRIVATE PAYLOAD')=='done'
    assert 'PRIVATE PAYLOAD' not in repr(sink.events[0])
