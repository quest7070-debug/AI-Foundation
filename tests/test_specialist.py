from ai_foundation.capabilities import BoundComputeCapability,FixedComputeTool
from ai_foundation.specialist import TextAnalysisSpecialist
class C:
 def __init__(self): self.calls=[]
 def compute(self,op,payload): self.calls.append((op,payload)); return payload[:4]
def test_specialist_owns_method_but_not_compute_authority():
 p=C(); cap=BoundComputeCapability(p,frozenset({'summarize'}))
 s=TextAnalysisSpecialist(FixedComputeTool(cap,'summarize'))
 assert s.summarize('abcdef')=='abcd'
 assert p.calls==[('summarize','abcdef')]
