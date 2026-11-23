from types import SimpleNamespace
from ai_foundation.agent import AgentRequest,PydanticAgentPort

class FakeAgent:
 def __init__(self): self.calls=[]
 def run_sync(self,text,**kwargs):
  self.calls.append((text,kwargs)); return SimpleNamespace(output='proposal')

def test_pydantic_adapter_is_thin_and_replaceable():
 a=FakeAgent(); p=PydanticAgentPort(a,model='test-model')
 assert p.run(AgentRequest('inspect only')).output=='proposal'
 assert a.calls==[('inspect only',{'model':'test-model'})]

def test_pydantic_adapter_passes_structured_message_history():
    from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart

    a = FakeAgent()
    p = PydanticAgentPort(a, model='test-model')

    history = (
        ModelRequest(parts=[UserPromptPart('remember KITE-7391')]),
        ModelResponse(parts=[TextPart('understood')]),
    )

    assert p.run(AgentRequest('what was the code?', message_history=history)).output == 'proposal'

    text, kwargs = a.calls[-1]
    assert text == 'what was the code?'
    assert kwargs['model'] == 'test-model'
    assert kwargs['message_history'] == history
