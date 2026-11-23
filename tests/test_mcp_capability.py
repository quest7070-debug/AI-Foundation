import pytest
from ai_foundation.mcp_capability import MCPToolGrant,MCPToolRegistry
class C:
 def __init__(self,server):self.server=server;self.calls=[]
 def discover(self):return {'safe':{'name':'safe'},'other':{'name':'other'}}
 def call(self,t,a):
  if t not in self.discover():raise ValueError('unknown')
  self.calls.append((t,a));return {'server':self.server,'tool':t}
def test_registered_generic_mcp_scope_selects_and_invokes_exact_server_tool():
 made=[]
 def f(server):c=C(server);made.append(c);return c
 r=MCPToolRegistry(f);r.register(MCPToolGrant('clock','server-a',frozenset({'safe'})))
 assert r.invoke('clock','safe',{'x':1})=={'server':'server-a','tool':'safe'}
 assert made[-1].calls==[('safe',{'x':1})]
 with pytest.raises(PermissionError):r.invoke('clock','other',{})
 with pytest.raises(PermissionError):r.invoke('missing','safe',{})
def test_duplicate_or_empty_grants_fail_closed():
 r=MCPToolRegistry(C);g=MCPToolGrant('x','s',frozenset({'safe'}));r.register(g)
 with pytest.raises(ValueError):r.register(g)
 with pytest.raises(ValueError):MCPToolGrant('','s',frozenset({'safe'}))
