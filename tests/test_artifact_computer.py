import pytest
from ai_foundation.artifact import *
from ai_foundation.computer_action import *
class A:
 def create(self,t,c): return 'created'
 def validate(self,t): return 'VERIFIED'
def test_artifact_requires_independent_validation():
 r=ArtifactSpecialist(A()).produce('x','c'); assert r.verified
class C:
 def __init__(self,observed='done'): self.method=None; self.observed=observed
 def act(self,m,a,t): self.method=m; return 'acted'
 def observe(self,t): return self.observed
def test_computer_prefers_strongest_available_method_and_readback():
 p=C(); s=ComputerActionSpecialist(p,frozenset({ActionMethod.VISION,ActionMethod.MCP}))
 assert s.perform('click','x','done')=='acted' and p.method is ActionMethod.MCP
def test_computer_fails_when_readback_disagrees():
 with pytest.raises(RuntimeError): ComputerActionSpecialist(C('wrong'),frozenset({ActionMethod.API})).perform('set','x','done')
