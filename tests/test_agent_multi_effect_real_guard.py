from ai_foundation.agent_tools import CapabilityAgentTools,ReadCapability,WriteCapability,GuardedToolGateway
from ai_foundation.core import CanonContract,GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.store import SQLiteGuardStore
class Port:
 def __init__(self): self.v={}; self.n=0
 def execute(self,p): self.n+=1; self.v[p.target]=p.text
 def observe(self,p): return self.v.get(p.target,'')
def test_real_guard_two_writes_same_agent_run(tmp_path):
 store=SQLiteGuardStore(tmp_path/'g.db'); port=Port(); guard=GuardCore(GuardState(),store=store)
 gw=GuardedToolGateway(guard,CanonContract('x','c1'),port)
 tools=CapabilityAgentTools(gw,'agent-run','c1',ReadCapability(str(tmp_path)),WriteCapability(str(tmp_path)))
 assert tools.write('a','1')=='VERIFIED_COMPLETE'
 assert tools.write('b','2')=='VERIFIED_COMPLETE'
 assert port.n==2

def test_replay_same_explicit_effect_id_is_idempotent(tmp_path):
 store=SQLiteGuardStore(tmp_path/'r.db'); port=Port(); guard=GuardCore(GuardState(),store=store)
 gw=GuardedToolGateway(guard,CanonContract('x','c1'),port)
 target=str(tmp_path/'a')
 assert gw.write(run_id='run',effect_id='run:e1',target=target,content='1',canon_revision='c1')=='VERIFIED_COMPLETE'
 assert gw.write(run_id='run',effect_id='run:e1',target=target,content='1',canon_revision='c1')=='VERIFIED_COMPLETE'
 assert port.n==1
 effect=store.load().effects['run:e1']; assert effect.run_id=='run' and effect.status.value=='VERIFIED'
