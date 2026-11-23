import inspect
from ai_foundation.agent_tools import BoundGuardedWriteTool,GuardedToolGateway
from ai_foundation.core import CanonContract
from ai_foundation.guard import GuardCore
from ai_foundation.store import SQLiteGuardStore

class Port:
 def __init__(self): self.value=''; self.calls=0
 def execute(self,p): self.calls+=1; self.value=p.text
 def observe(self,p): return self.value

def test_model_visible_signature_contains_no_authority_fields(tmp_path):
 p=Port(); s=SQLiteGuardStore(tmp_path/'g.db')
 bound=BoundGuardedWriteTool(GuardedToolGateway(GuardCore(s.load(),100,s),CanonContract('repo','c1'),p),'trusted-run','c1')
 assert list(inspect.signature(bound.__call__).parameters)==['target','content']
 assert bound('x','ok')=='VERIFIED_COMPLETE'
 assert s.load().effects['trusted-run'].run_id=='trusted-run'
