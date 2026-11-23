import inspect
import pytest
from ai_foundation.agent_tools import ScopedAgentTools,WriteCapability,GuardedToolGateway
from ai_foundation.core import CanonContract
from ai_foundation.guard import GuardCore
from ai_foundation.store import SQLiteGuardStore

class Port:
 def __init__(self): self.v=''; self.calls=0
 def execute(self,p): self.calls+=1; self.v=p.text
 def observe(self,p): return self.v

def make(tmp_path):
 s=SQLiteGuardStore(tmp_path/'g.db'); p=Port(); root=tmp_path/'allowed'; root.mkdir()
 t=ScopedAgentTools(GuardedToolGateway(GuardCore(s.load(),10,s),CanonContract('r','c1'),p),'trusted','c1',WriteCapability(str(root)))
 return s,p,t,root

def test_model_schema_exposes_no_scope_or_authority(tmp_path):
 _,_,t,_=make(tmp_path)
 assert list(inspect.signature(t.write).parameters)==['target','content']

def test_scoped_write_allows_inside_root(tmp_path):
 s,p,t,root=make(tmp_path)
 assert t.write(str(root/'ok.txt'),'ok')=='VERIFIED_COMPLETE'
 assert p.calls==1 and s.load().effects['trusted'].target==str((root/'ok.txt').resolve())

def test_scoped_write_denies_parent_escape_before_guard(tmp_path):
 s,p,t,root=make(tmp_path)
 with pytest.raises(PermissionError): t.write(str(root/'..'/'escape.txt'),'bad')
 assert p.calls==0 and not s.load().effects

def test_scoped_write_denies_absolute_outside_target(tmp_path):
 s,p,t,_=make(tmp_path)
 with pytest.raises(PermissionError): t.write('/tmp/agent-escape.txt','bad')
 assert p.calls==0 and not s.load().effects
