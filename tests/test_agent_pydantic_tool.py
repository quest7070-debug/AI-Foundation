from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from ai_foundation.agent import AgentRequest,PydanticAgentPort
from ai_foundation.agent_tools import BoundGuardedWriteTool,GuardedToolGateway
from ai_foundation.core import CanonContract
from ai_foundation.guard import GuardCore
from ai_foundation.store import SQLiteGuardStore

class Port:
 def __init__(self): self.value=''; self.calls=0
 def execute(self,p): self.calls+=1; self.value=p.text
 def observe(self,p): return self.value

def test_real_pydantic_function_tool_has_no_model_controlled_authority(tmp_path):
 store=SQLiteGuardStore(tmp_path/'g.db'); effect=Port()
 gateway=GuardedToolGateway(GuardCore(store.load(),100,store),CanonContract('repo','trusted-rev'),effect)
 bound=BoundGuardedWriteTool(gateway,'trusted-run','trusted-rev')
 agent=Agent(TestModel(call_tools=['guarded_write']))
 @agent.tool_plain(name='guarded_write')
 def guarded_write(target:str,content:str)->str:
  return bound(target,content)
 out=PydanticAgentPort(agent).run(AgentRequest('write through the provided tool'))
 assert out.output and effect.calls==1
 state=store.load(); assert set(state.effects)=={'trusted-run'}
 assert state.effects['trusted-run'].status.value=='VERIFIED'
