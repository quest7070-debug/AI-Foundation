from ai_foundation.capabilities import BoundComputeCapability,FixedComputeTool
from ai_foundation.data_specialist import DataSpecialist
class P:
 def compute(self,o,p): return f'{o}:{p}'
def test_data_specialist_operation_is_host_bound():
 r=DataSpecialist(FixedComputeTool(BoundComputeCapability(P(),frozenset({'analyze'})),'analyze')).analyze('rows')
 assert r.operation=='analyze' and r.output=='analyze:rows'
