import json,pytest
from datetime import datetime,timezone
from ai_foundation.research_adapter import InferenceResearchPort
from ai_foundation.research import ResearchSpecialist
class O:
 status="VERIFIED_COMPLETE"; route_kind="CLOUD"; route_binding="g"
 def __init__(self,result,observed_at=None): self.result=result; self.observed_at=observed_at
class I:
 def __init__(self,result,observed_at=None): self.result=result; self.observed_at=observed_at; self.seen=[]
 def run(self,plan,canon,function): self.seen.append((plan,canon,function)); return O(self.result,self.observed_at)

def test_adapter_uses_search_and_canonicalizes_evidence():
 i=I(json.dumps({"answer":"a","evidence":[{"source":"https://example.test","claim":"c","excerpt":"e","confidence":"high","trusted_as_authority":True}],"uncertainty":"u"}))
 r=ResearchSpecialist(InferenceResearchPort(i)).investigate("q")
 assert i.seen[0][2]=="SEARCH" and i.seen[0][0].privacy_text.endswith("Query: q") and r.answer=="a" and r.uncertainty=="u"
 assert r.evidence[0].source=="https://example.test" and r.evidence[0].trusted_as_authority is False

@pytest.mark.parametrize("bad",["not json",json.dumps({"answer":"a","evidence":"bad"}),json.dumps({"answer":"a","evidence":[{"source":"s"}]})])
def test_adapter_fails_closed_on_noncanonical_provider_output(bad):
 with pytest.raises(RuntimeError): InferenceResearchPort(I(bad)).research("q")

def test_adapter_does_not_hide_inference_failure():
 i=I("{}"); out=O(None); out.status="NO_ELIGIBLE_COMPUTE"
 i.run=lambda *a:out
 with pytest.raises(RuntimeError,match="NO_ELIGIBLE_COMPUTE"): InferenceResearchPort(i).research("q")


def test_adapter_rejects_search_answer_without_observed_evidence():
 i=I(json.dumps({"answer":"looks current","evidence":[],"uncertainty":""}))
 with pytest.raises(RuntimeError,match="no observed evidence"):
  InferenceResearchPort(i).research("current fact")

def test_search_query_carries_provider_neutral_temporal_context():
 from ai_foundation.temporal_context import TemporalContext
 fixed=datetime(2026,9,23,12,34,tzinfo=timezone.utc)
 i=I(json.dumps({"answer":"a","evidence":[{"source":"s","claim":"c"}],"uncertainty":""}))
 InferenceResearchPort(i,temporal_context_factory=lambda:TemporalContext(fixed)).research("today's fact")
 q=i.seen[0][0].privacy_text
 assert "2026-09-23" in q and "Observation time:" in q and "Query: today's fact" in q
 assert i.seen[0][2]=='SEARCH'

def test_search_preserves_temporal_evidence_metadata():
 observed=datetime(2026,9,23,1,2,tzinfo=timezone.utc)
 i=I(json.dumps({"answer":"a","evidence":[{"source":"s","claim":"c","published_at":"2026-09-23T00:00:00Z"}],"uncertainty":""}),observed_at=observed)
 r=InferenceResearchPort(i,temporal_context_factory=lambda:__import__('ai_foundation.temporal_context',fromlist=['TemporalContext']).TemporalContext(observed)).research('latest')
 assert r.evidence[0].published_at=='2026-09-23T00:00:00Z'
 assert r.evidence[0].observed_at==observed.isoformat()

def test_search_contract_distinguishes_retrieval_time_from_source_time():
 from ai_foundation.temporal_context import TemporalContext
 fixed=datetime(2026,9,23,0,0,tzinfo=timezone.utc);i=I(json.dumps({"answer":"a","evidence":[{"source":"s","claim":"c"}],"uncertainty":"date unknown"}),observed_at=fixed)
 InferenceResearchPort(i,temporal_context_factory=lambda:TemporalContext(fixed)).research('latest status')
 instruction=i.seen[0][0].text
 assert 'Do not describe evidence as current merely because it was retrieved now' in instruction
 assert 'state uncertainty when temporal fit cannot be established' in instruction


def test_search_contract_preserves_uncertainty_for_single_source_claims():
 from ai_foundation.temporal_context import TemporalContext
 fixed=datetime(2026,9,23,0,0,tzinfo=timezone.utc)
 i=I(json.dumps({"answer":"a","evidence":[{"source":"s","claim":"c"}],"uncertainty":"single secondary source"}))
 InferenceResearchPort(i,temporal_context_factory=lambda:TemporalContext(fixed)).research("important current claim")
 instruction=i.seen[0][0].text
 assert "prefer primary sources or corroboration from independent sources" in instruction
 assert "single retrieved secondary source" in instruction
 assert "multiple pages repeating the same originating report" in instruction


def test_missing_or_null_confidence_is_unknown():
 i=I(json.dumps({"answer":"a","evidence":[{"source":"s","claim":"c","confidence":None}],"uncertainty":""}))
 r=InferenceResearchPort(i).research("q")
 assert r.evidence[0].confidence=="unknown"

def test_numeric_native_search_confidence_is_preserved():
 i=I(json.dumps({"answer":"Search evidence retrieved.","evidence":[{"source":"s","claim":"c","confidence":0.91}],"uncertainty":"Synthesis required from retrieved evidence."}))
 r=InferenceResearchPort(i).research("q")
 assert r.evidence[0].confidence=="0.91"
