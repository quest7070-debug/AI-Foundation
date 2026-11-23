from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from ai_foundation.agent import AgentRequest,PydanticAgentPort
from ai_foundation.agent_tools import CapabilityAgentTools,ReadCapability,WriteCapability,GuardedToolGateway
from ai_foundation.core import CanonContract
from ai_foundation.guard import GuardCore
from ai_foundation.store import SQLiteGuardStore

class Port:
 def __init__(self): self.v='before'; self.execs=0; self.reads=0
 def execute(self,p): self.execs+=1; self.v=p.text
 def observe(self,p): self.reads+=1; return self.v

def setup(tmp_path, call_tools):
 store=SQLiteGuardStore(tmp_path/'g.db'); port=Port(); root=tmp_path/'scope'; root.mkdir()
 tools=CapabilityAgentTools(GuardedToolGateway(GuardCore(store.load(),10,store),CanonContract('r','a'),port),'trusted','a',ReadCapability(str(root)),WriteCapability(str(root)))
 agent=Agent(TestModel(call_tools=call_tools)); agent.tool_plain(tools.read); agent.tool_plain(tools.write)
 return store,port,root,agent

def test_real_agent_read_only_creates_no_effect(tmp_path):
 store,port,root,agent=setup(tmp_path,['read'])
 out=PydanticAgentPort(agent).run(AgentRequest('inspect using read'))
 assert out.output and port.reads==1 and port.execs==0 and not store.load().effects

def test_real_agent_write_is_guard_effect(tmp_path):
 store,port,root,agent=setup(tmp_path,['write'])
 out=PydanticAgentPort(agent).run(AgentRequest('change using write'))
 assert out.output and port.execs==1
 assert store.load().effects['trusted:effect:1'].status.value=='VERIFIED'

def test_real_agent_read_then_write_only_write_creates_effect(tmp_path):
 store,port,root,agent=setup(tmp_path,['read','write'])
 out=PydanticAgentPort(agent).run(AgentRequest('inspect then change'))
 assert out.output and port.reads>=2 and port.execs==1
 assert set(store.load().effects)=={'trusted:effect:1'}
