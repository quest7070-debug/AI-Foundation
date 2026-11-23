from ai_foundation.core import CanonContract, GuardState, TaskPlan
from ai_foundation.evaluation import DeterministicEvaluator, EvalCase, summarize_gate
from ai_foundation.guard import GuardCore
from ai_foundation.instrumentation import ObservedGuard
from ai_foundation.observability import InMemoryTraceSink, Tracer
from ai_foundation.run_report import build_run_report

class Port:
    def __init__(self): self.v=''; self.n=0
    def execute(self,p): self.n+=1; self.v=p.text
    def observe(self,p): return self.v

def test_security_recovery_gate_is_evidence_linked_and_deterministic():
    sink=InMemoryTraceSink(); guard=ObservedGuard(GuardCore(GuardState()),Tracer(sink)); port=Port()
    plan=TaskPlan('phase-e','write','repo',text='ok',canon_revision='c',effect_id='effect-e')
    result=guard.execute(plan,CanonContract('x','c'),port,'ok')
    evals=DeterministicEvaluator().run((
        EvalCase('verified-readback',lambda: result=='VERIFIED_COMPLETE' and port.v=='ok',('effect:effect-e','readback:repo')),
        EvalCase('exactly-once',lambda: port.n==1,('effect:effect-e',)),
        EvalCase('no-trace-payload',lambda: all('ok' not in repr(e.attributes) for e in sink.events),('trace:safe-metadata',)),
    ))
    gate=summarize_gate(evals); report=build_run_report(sink.events,evals)
    assert gate.passed and report.passed
    assert 'effect:effect-e' in report.evidence_ids and 'readback:repo' in report.evidence_ids
