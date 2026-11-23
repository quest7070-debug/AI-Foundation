from dataclasses import dataclass
from .evaluation import EvalResult
from .observability import TraceEvent

@dataclass(frozen=True)
class EvidenceLinkedRunReport:
    trace_id: str
    span_count: int
    error_spans: int
    evidence_ids: tuple[str, ...]
    eval_results: tuple[EvalResult, ...]

    @property
    def passed(self):
        return self.span_count > 0 and self.error_spans == 0 and all(r.passed for r in self.eval_results)

def build_run_report(events, eval_results=()):
    events=tuple(events); results=tuple(eval_results)
    trace_ids={e.trace_id for e in events}
    if len(trace_ids) > 1: raise ValueError('report requires one trace')
    evidence=[]
    for event in events:
        for item in event.evidence_ids:
            if item not in evidence: evidence.append(item)
    for result in results:
        for item in result.evidence:
            if item not in evidence: evidence.append(item)
    return EvidenceLinkedRunReport(next(iter(trace_ids),'') ,len(events),sum(e.status=='ERROR' for e in events),tuple(evidence),results)
