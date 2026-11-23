from ai_foundation.agent_tools import GuardedToolGateway
from ai_foundation.core import CanonContract,TaskPlan
from ai_foundation.guard import GuardCore
from ai_foundation.store import SQLiteGuardStore

class Port:
 def __init__(self): self.value=''; self.calls=0
 def execute(self,p): self.calls+=1; self.value=p.text
 def observe(self,p): return self.value

def test_agent_gateway_effect_must_pass_guard(tmp_path):
 s=SQLiteGuardStore(tmp_path/'g.db'); port=Port(); g=GuardCore(s.load(),100,s)
 tool=GuardedToolGateway(g,CanonContract('repo','c1'),port)
 assert tool.write(run_id='a',target='x',content='ok',canon_revision='c1')=='VERIFIED_COMPLETE'
 assert port.calls==1 and s.load().effects['a'].status.value=='VERIFIED'

def test_agent_gateway_cannot_bypass_canon(tmp_path):
 s=SQLiteGuardStore(tmp_path/'g.db'); port=Port()
 tool=GuardedToolGateway(GuardCore(s.load(),100,s),CanonContract('repo','c1'),port)
 assert tool.write(run_id='a',target='x',content='bad',canon_revision='attacker')=='WAITING_HUMAN'
 assert port.calls==0 and not s.load().effects

def test_agent_gateway_approval_still_blocks_high_impact(tmp_path):
 s=SQLiteGuardStore(tmp_path/'g.db'); port=Port(); g=GuardCore(s.load(),100,s)
 plan=TaskPlan('mail','send_email','person@example.invalid',text='hello',canon_revision='c1')
 assert g.execute(plan,CanonContract('repo','c1'),port,'hello')=='WAITING_HUMAN'
 assert port.calls==0
