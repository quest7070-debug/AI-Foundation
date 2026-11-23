from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from ai_foundation.agent import AgentRequest,PydanticAgentPort
from ai_foundation.capabilities import BoundComputeCapability,FixedComputeTool
class Compute:
 def __init__(self): self.calls=[]
 def compute(self,op,payload): self.calls.append((op,payload)); return f'{op}:{payload}'
def test_real_pydantic_agent_uses_bounded_compute():
 p=Compute(); c=BoundComputeCapability(p,frozenset({'summarize'})); tool=FixedComputeTool(c,'summarize')
 agent=Agent(TestModel(call_tools=['run'])); agent.tool_plain(tool.run)
 out=PydanticAgentPort(agent).run(AgentRequest('compute with the available operation'))
 assert out.output and p.calls==[('summarize','a')]
