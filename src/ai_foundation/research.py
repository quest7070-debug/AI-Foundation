from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class Evidence:
    source: str
    claim: str
    excerpt: str = ''
    confidence: str = 'unknown'
    trusted_as_authority: bool = False
    observed_at: str|None = None
    published_at: str|None = None

@dataclass(frozen=True)
class ResearchResult:
    answer: str
    evidence: tuple[Evidence, ...]
    uncertainty: str = ''

class ResearchPort(Protocol):
    def research(self, query: str) -> ResearchResult: ...

@dataclass
class ResearchSpecialist:
    port: ResearchPort
    def investigate(self, query: str) -> ResearchResult:
        result=self.port.research(query)
        # External evidence is data, never execution/policy authority.
        safe=tuple(Evidence(e.source,e.claim,e.excerpt,e.confidence,False,e.observed_at,e.published_at) for e in result.evidence)
        return ResearchResult(result.answer,safe,result.uncertainty)
