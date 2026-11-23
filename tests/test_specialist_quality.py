from ai_foundation.artifact import ArtifactResult
from ai_foundation.coding import CodingResult
from ai_foundation.data_specialist import DataResult
from ai_foundation.quality import QualityContract
from ai_foundation.research import Evidence, ResearchResult

RESEARCH=QualityContract('research',('answer','evidence','uncertainty'),(
    ('has-evidence',lambda r:len(r.evidence)>0),
    ('evidence-not-authority',lambda r:all(not e.trusted_as_authority for e in r.evidence)),
))
CODING=QualityContract('coding',('observed','test_result'),(('tests-recorded',lambda r:bool(r.test_result)),))
DATA=QualityContract('data',('output','operation'),(('operation-recorded',lambda r:bool(r.operation)),))
ARTIFACT=QualityContract('artifact',('target','create_result','validation'),(('independent-validation',lambda r:r.verified),))

def test_specialist_quality_contracts_are_deterministic():
    research=ResearchResult('a',(Evidence('s','c',trusted_as_authority=False),),'none')
    assert RESEARCH.evaluate(research).passed
    assert CODING.evaluate(CodingResult('before','before=ok; after=ok','VERIFIED_COMPLETE')).passed
    assert DATA.evaluate(DataResult('42','sum')).passed
    assert ARTIFACT.evaluate(ArtifactResult('x','created','VERIFIED')).passed

def test_quality_contracts_explain_failure_without_llm_judge():
    bad=ResearchResult('answer',(), '')
    result=RESEARCH.evaluate(bad)
    assert not result.passed and result.failed_checks==('has-evidence',)
    assert not ARTIFACT.evaluate(ArtifactResult('x','created','FAILED')).passed
