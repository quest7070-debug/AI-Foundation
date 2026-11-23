from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from ai_foundation.agent import AgentRequest,PydanticAgentPort
from ai_foundation.agent_tools import BoundAgentTools,GuardedToolGateway
from ai_foundation.core import CanonContract
from ai_foundation.guard import GuardCore
from ai_foundation.store import SQLiteGuardStore

class Port:
 def __init__(self): self.v=''; self.calls=0
 def execute(self,p): self.calls+=1; self.v=p.text
 def observe(self,p): return self.v

def test_real_pydantic_tool_cannot_supply_authority_fields(tmp_path):
 s=SQLiteGuardStore(tmp_path/'g.db'); p=Port()
 bound=BoundAgentTools(GuardedToolGateway(GuardCore(s.load(),10,s),CanonContract('r','c1'),p),'trusted-agent-run','c1')
 agent=Agent(TestModel(call_tools=['write']))
 agent.tool_plain(bound.write)
 out=PydanticAgentPort(agent).run(AgentRequest('use write'))
 assert out.output and p.calls==1
 assert set(s.load().effects)=={'trusted-agent-run'}

def test_scoped_production_agent_factory_keeps_scope_outside_model(tmp_path):
 from ai_foundation.agent import scoped_pydantic_agent,AgentRequest
 from ai_foundation.agent_tools import CapabilityAgentTools,GuardedToolGateway,ReadCapability,WriteCapability
 p=Port();s=SQLiteGuardStore(tmp_path/'scope.db')
 tools=CapabilityAgentTools(GuardedToolGateway(GuardCore(s.load(),10,s),CanonContract('r','c1'),p),'agent-scope','c1',ReadCapability(str(tmp_path)),WriteCapability(str(tmp_path)))
 out=scoped_pydantic_agent(TestModel(call_tools=['write']),tools).run(AgentRequest('use write'))
 assert out.output and p.calls==1
