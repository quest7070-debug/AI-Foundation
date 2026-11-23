from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from ai_foundation.agent import AgentRequest,PydanticAgentPort
from ai_foundation.capabilities import BoundComputeCapability,FixedComputeTool
from ai_foundation.specialist import TextAnalysisSpecialist
class C:
 def __init__(self): self.calls=[]
 def compute(self,op,payload): self.calls.append((op,payload)); return 'summary'
def test_real_agent_calls_first_specialist_through_bound_compute():
 p=C(); spec=TextAnalysisSpecialist(FixedComputeTool(BoundComputeCapability(p,frozenset({'summarize'})),'summarize'))
 agent=Agent(TestModel(call_tools=['summarize'])); agent.tool_plain(spec.summarize)
 assert PydanticAgentPort(agent).run(AgentRequest('summarize this')).output
 assert p.calls==[('summarize','a')]
