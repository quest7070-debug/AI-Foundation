import pytest
from ai_foundation.capabilities import CapabilityKind,CapabilitySpec,BoundComputeCapability
class Compute:
 def __init__(self): self.calls=0
 def compute(self,op,payload): self.calls+=1; return f'{op}:{payload}'
def test_three_generic_capability_kinds_are_explicit():
 assert {x.value for x in CapabilityKind}=={'READ','COMPUTE','EFFECT'}
 assert CapabilitySpec('search',CapabilityKind.READ).kind is CapabilityKind.READ
def test_compute_is_bound_to_host_allowed_operations():
 p=Compute(); c=BoundComputeCapability(p,frozenset({'summarize'}))
 assert c.run('summarize','x')=='summarize:x' and p.calls==1
 with pytest.raises(PermissionError): c.run('shell','rm -rf /')
 assert p.calls==1
