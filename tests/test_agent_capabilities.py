import inspect,pytest
from ai_foundation.agent_tools import *
from ai_foundation.core import CanonContract
from ai_foundation.guard import GuardCore
from ai_foundation.store import SQLiteGuardStore
class Port:
 def __init__(self): self.v='observed'; self.calls=0; self.observes=0
 def execute(self,p): self.calls+=1; self.v=p.text
 def observe(self,p): self.observes+=1; return self.v
def make(tmp):
 s=SQLiteGuardStore(tmp/'g.db'); p=Port(); r=tmp/'scope'; r.mkdir()
 g=GuardedToolGateway(GuardCore(s.load(),10,s),CanonContract('r','c1'),p)
 return s,p,CapabilityAgentTools(g,'trusted','c1',ReadCapability(str(r)),WriteCapability(str(r))),r

def test_read_is_observational_and_creates_no_effect(tmp_path):
 s,p,t,r=make(tmp_path); assert t.read(str(r/'x'))=='observed'
 assert p.observes==1 and p.calls==0 and not s.load().effects

def test_read_scope_escape_denied(tmp_path):
 s,p,t,r=make(tmp_path)
 with pytest.raises(PermissionError): t.read(str(r/'..'/'secret'))
 assert p.observes==0 and not s.load().effects

def test_write_still_crosses_guard_and_persists_effect(tmp_path):
 s,p,t,r=make(tmp_path); assert t.write(str(r/'x'),'changed')=='VERIFIED_COMPLETE'
 assert p.calls==1 and s.load().effects['trusted:effect:1'].status.value=='VERIFIED'

def test_model_visible_capability_schema_has_no_authority_fields(tmp_path):
 _,_,t,_=make(tmp_path)
 assert list(inspect.signature(t.read).parameters)==['target']
 assert list(inspect.signature(t.write).parameters)==['target','content']
