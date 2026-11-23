from pathlib import Path
from ai_foundation.agent_tools import CapabilityAgentTools,ReadCapability,WriteCapability,GuardedToolGateway
from ai_foundation.core import CanonContract,TaskPlan
class Port:
 def __init__(self): self.values={}; self.execs=0
 def execute(self,p): self.execs+=1; self.values[p.target]=p.text; return p.text
 def observe(self,p): return self.values.get(p.target,'')
class Guard:
 def __init__(self): self.ids=[]
 def execute(self,p,canon,port,content): self.ids.append(p.run_id); port.execute(p); return 'VERIFIED_COMPLETE'
def test_two_writes_same_agent_run_are_currently_distinguishable_only_by_target(tmp_path):
 p=Port(); g=Guard(); gw=GuardedToolGateway(g,CanonContract('x','c1'),p)
 tools=CapabilityAgentTools(gw,'agent-run','c1',ReadCapability(str(tmp_path)),WriteCapability(str(tmp_path)))
 assert tools.write('a','1')=='VERIFIED_COMPLETE'
 assert tools.write('b','2')=='VERIFIED_COMPLETE'
 assert g.ids==['agent-run','agent-run']
 assert p.execs==2
