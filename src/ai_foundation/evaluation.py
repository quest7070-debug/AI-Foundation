from dataclasses import dataclass
from typing import Callable

@dataclass(frozen=True)
class EvalCase:
    name: str
    check: Callable[[], bool]
    evidence: tuple[str, ...] = ()

@dataclass(frozen=True)
class EvalResult:
    name: str
    passed: bool
    evidence: tuple[str, ...]
    detail: str = ''

class DeterministicEvaluator:
    """Default evaluator: observable contracts first, no model judge."""
    def run(self,cases):
        out=[]
        for case in cases:
            try:
                passed=case.check() is True
                out.append(EvalResult(case.name,passed,case.evidence,'' if passed else 'check returned false'))
            except Exception as exc:
                out.append(EvalResult(case.name,False,case.evidence,type(exc).__name__))
        return tuple(out)

class SemanticEvaluator:
    """Explicit opt-in boundary for cases deterministic checks cannot decide."""
    def __init__(self,judge): self.judge=judge
    def run(self,name,payload,evidence=()):
        verdict=self.judge(payload)
        if not isinstance(verdict,bool): raise TypeError('semantic judge must return bool')
        return EvalResult(name,verdict,tuple(evidence),'semantic')

@dataclass(frozen=True)
class GateSummary:
    passed: bool
    total: int
    failed: tuple[str, ...]
    evidence: tuple[str, ...]

def summarize_gate(results):
    results=tuple(results); failed=tuple(r.name for r in results if not r.passed)
    evidence=[]
    for r in results:
        for item in r.evidence:
            if item not in evidence: evidence.append(item)
    return GateSummary(not failed,len(results),failed,tuple(evidence))
