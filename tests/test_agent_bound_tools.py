import inspect
from ai_foundation.agent_tools import BoundAgentTools,GuardedToolGateway
from ai_foundation.core import CanonContract
from ai_foundation.guard import GuardCore
from ai_foundation.store import SQLiteGuardStore

class Port:
 def __init__(self): self.v=''; self.calls=0
 def execute(self,p): self.calls+=1; self.v=p.text
 def observe(self,p): return self.v

def test_model_visible_write_schema_has_no_authority_fields(tmp_path):
 s=SQLiteGuardStore(tmp_path/'g.db'); b=BoundAgentTools(GuardedToolGateway(GuardCore(s.load(),10,s),CanonContract('r','c1'),Port()),'trusted-run','c1')
 assert list(inspect.signature(b.write).parameters)==['target','content']

def test_bound_authority_is_used_for_effect(tmp_path):
 s=SQLiteGuardStore(tmp_path/'g.db'); p=Port(); b=BoundAgentTools(GuardedToolGateway(GuardCore(s.load(),10,s),CanonContract('r','c1'),p),'trusted-run','c1')
 assert b.write('x','ok')=='VERIFIED_COMPLETE'
 assert p.calls==1 and 'trusted-run' in s.load().effects
