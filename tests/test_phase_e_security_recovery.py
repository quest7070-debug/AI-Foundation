from ai_foundation.core import CanonContract, GuardState, TaskPlan
from ai_foundation.evaluation import DeterministicEvaluator, EvalCase, summarize_gate
from ai_foundation.guard import GuardCore
from ai_foundation.instrumentation import ObservedGuard
from ai_foundation.observability import InMemoryTraceSink, Tracer
from ai_foundation.run_report import build_run_report
from ai_foundation.store import SQLiteGuardStore

class Port:
    def __init__(self): self.v='old'; self.n=0
    def execute(self,p): self.n+=1; self.v=p.text
    def observe(self,p): return self.v

def test_recovery_replay_gate_proves_no_duplicate_effect(tmp_path):
    store=SQLiteGuardStore(tmp_path/'g.db'); port=Port(); sink=InMemoryTraceSink(); tracer=Tracer(sink)
    plan=TaskPlan('r','write','repo',text='new',canon_revision='c',effect_id='e')
    first=ObservedGuard(GuardCore(store.load(),100,store),tracer).execute(plan,CanonContract('x','c'),port,'new')
    second=ObservedGuard(GuardCore(store.load(),100,store),tracer).execute(plan,CanonContract('x','c'),port,'new')
    evals=DeterministicEvaluator().run((
        EvalCase('both-verified',lambda:first==second=='VERIFIED_COMPLETE',('effect:e',)),
        EvalCase('no-duplicate-effect',lambda:port.n==1,('effect:e','readback:repo')),
        EvalCase('durable-verified',lambda:store.load().effects['e'].status.value=='VERIFIED',('store:effect:e',)),
    ))
    assert summarize_gate(evals).passed
    # Calls are separate top-level traces; each report remains independently attributable.
    assert len({e.trace_id for e in sink.events})==2
    assert all(build_run_report((e,),evals).passed for e in sink.events)

def test_security_denial_gate_proves_zero_external_effect():
    class DenyCredential:
        def authorize(self,binding,target): return False
    sink=InMemoryTraceSink(); port=Port(); plan=TaskPlan('deny','write','repo',text='new',canon_revision='c',credential_binding='missing')
    result=ObservedGuard(GuardCore(GuardState(),credential_boundary=DenyCredential()),Tracer(sink)).execute(plan,CanonContract('x','c'),port,'new')
    evals=DeterministicEvaluator().run((
        EvalCase('denied',lambda:result=='DENY',('authorization:deny',)),
        EvalCase('zero-effect',lambda:port.n==0,('effect:none',)),
    ))
    assert summarize_gate(evals).passed and build_run_report(sink.events,evals).passed
