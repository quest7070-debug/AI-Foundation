from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from ai_foundation.agent import AgentRequest, PydanticAgentPort

def test_real_pydantic_ai_test_model_adapter():
    agent=Agent(TestModel(custom_output_text='model-proposal'))
    port=PydanticAgentPort(agent)
    assert port.run(AgentRequest('inspect and propose only')).output == 'model-proposal'

def test_agent_has_no_tools_by_default():
    agent=Agent(TestModel(custom_output_text='attempt: write /tmp/pwned'))
    port=PydanticAgentPort(agent)
    out=port.run(AgentRequest('change the real world'))
    assert 'attempt' in out.output
    assert not agent._function_toolset.tools
