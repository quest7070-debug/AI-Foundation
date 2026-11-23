import json
from types import SimpleNamespace
import pytest
from pydantic_ai import Agent
from ai_foundation.routed_agent_model import AgentRouteUnavailable, foundation_agent_model

class Registry:
 def __init__(self,provider):self.provider=provider
 def credential(self,b):return {'provider':self.provider}
class Router:
 def __init__(self,routes,provider='OPENROUTER'):
  self.routes=list(routes);self.settings=SimpleNamespace(registry=Registry(provider))
 def choose(self,function,exclude=()):
  for r in self.routes:
   if r.binding not in exclude:return r
  return SimpleNamespace(binding=None)
class Cloud:
 def __init__(self,body):self.body=body if isinstance(body,list) else [body];self.payload=None;self.i=0
 def invoke_for_function(self,b,payload,f):
  self.payload=payload; row=self.body[min(self.i,len(self.body)-1)];self.i+=1;return json.dumps(row)

def test_routed_agent_model_preserves_tool_schema_and_foundation_route():
 cloud=Cloud([{'model':'x','choices':[{'message':{'tool_calls':[{'id':'c1','type':'function','function':{'name':'search','arguments':'{\"query\":\"now\"}'}}]}}]}, {'model':'x','choices':[{'message':{'content':'fresh answer'}}]}])
 r=Router([SimpleNamespace(binding='b',kind='CLOUD',model=None)])
 model=foundation_agent_model(r,lambda b:cloud,object())
 a=Agent(model)
 @a.tool_plain
 def search(query:str)->str:return 'fresh'
 out=a.run_sync('weather')
 assert out.output=='fresh answer'
 # Pydantic AI remains the semantic scheduler after a tool result: available tools
 # stay advertised so it may request another independent tool call. Provider-neutral
 # history still prevents a prior provider's tool-call protocol from leaking.
 assert cloud.payload['tools'][0]['function']['name']=='search'
 assert [m['role'] for m in cloud.payload['messages']][-1]=='tool'
 assert any(m.get('role')=='assistant' and m.get('tool_calls') for m in cloud.payload['messages'])

def test_routed_agent_model_attempts_tool_capable_gemini_transport():
 gem=Cloud({'candidates':[{'content':{'parts':[{'text':'no tools'}]}}]})
 ok=Cloud({'model':'x','choices':[{'message':{'content':'answer'}}]})
 routes=[SimpleNamespace(binding='g',kind='CLOUD',model=None),SimpleNamespace(binding='o',kind='CLOUD',model=None)]
 r=Router(routes)
 r.settings.registry=SimpleNamespace(credential=lambda b:{'provider':'GEMINI' if b=='g' else 'OPENROUTER'})
 model=foundation_agent_model(r,lambda b:gem if b=='g' else ok,object())
 a=Agent(model)
 @a.tool_plain
 def search(query:str)->str:return 'x'
 assert a.run_sync('hello').output=='answer'
 assert gem.payload is not None and gem.payload["tools"][0]["function"]["name"]=="search"

def test_routed_agent_model_traces_initial_and_final_model_calls():
 from ai_foundation.observability import InMemoryTraceSink,Tracer
 cloud=Cloud([{'model':'x','choices':[{'message':{'tool_calls':[{'id':'c1','type':'function','function':{'name':'search','arguments':'{\"query\":\"now\"}'}}]}}]}, {'model':'x','choices':[{'message':{'content':'fresh answer'}}]}])
 r=Router([SimpleNamespace(binding='b',kind='CLOUD',model=None)])
 sink=InMemoryTraceSink(); model=foundation_agent_model(r,lambda b:cloud,object(),tracer=Tracer(sink)); a=Agent(model)
 @a.tool_plain
 def search(query:str)->str:return 'fresh'
 assert a.run_sync('weather').output=='fresh answer'
 calls=[e for e in sink.events if e.name=='agent.model_call']
 assert [e.attributes['phase'] for e in calls]==['initial','tool_followup']
 assert all(e.attributes['route_binding']=='b' for e in calls)
 assert all(e.attributes['tool_count']=='1' for e in calls)
 assert all(e.attributes['tool_names']=='search' for e in calls)
 assert all(e.ended_ns>=e.started_ns for e in calls)

def test_agent_can_schedule_multiple_tools_after_first_tool_result():
 cloud=Cloud([
  {'model':'x','choices':[{'message':{'tool_calls':[{'id':'c1','type':'function','function':{'name':'search','arguments':'{\"query\":\"first\"}'}}]}}]},
  {'model':'x','choices':[{'message':{'tool_calls':[{'id':'c2','type':'function','function':{'name':'search','arguments':'{\"query\":\"second\"}'}}]}}]},
  {'model':'x','choices':[{'message':{'content':'combined answer'}}]},
 ])
 r=Router([SimpleNamespace(binding='b',kind='CLOUD',model=None)])
 model=foundation_agent_model(r,lambda b:cloud,object())
 a=Agent(model)
 seen=[]
 @a.tool_plain
 def search(query:str)->str:
  seen.append(query);return 'result:'+query
 out=a.run_sync('compare two current facts')
 assert out.output=='combined answer'
 assert seen==['first','second']
 assert cloud.i==3
 assert cloud.payload['tools'][0]['function']['name']=='search'

def test_real_request_failure_uses_canonical_next_route_not_synthetic_probe():
 class FailThenRecover:
  def __init__(self,b): self.b=b
  def invoke_for_function(self,b,payload,fn):
   if b=='first': raise RuntimeError('real request failed')
   return json.dumps({'model':b,'choices':[{'message':{'content':'recovered'},'finish_reason':'stop'}]})
 routes=[SimpleNamespace(binding='first',kind='CLOUD',model=None),SimpleNamespace(binding='second',kind='CLOUD',model=None)]
 r=Router(routes); model=foundation_agent_model(r,lambda b:FailThenRecover(b),object())
 assert Agent(model).run_sync('hello').output=='recovered'


def test_agent_phase_does_not_create_phase_specific_route_selection():
 class PhaseAwareRouter(Router):
  def __init__(self,routes):
   super().__init__(routes);self.phases=[]
  def choose(self,function,exclude=(),phase=None):
   self.phases.append(phase)
   return super().choose(function,exclude)
 cloud=Cloud([
  {'model':'x','choices':[{'message':{'tool_calls':[{'id':'c1','type':'function','function':{'name':'search','arguments':'{"query":"now"}'}}]}}]},
  {'model':'x','choices':[{'message':{'content':'done'}}]},
 ])
 r=PhaseAwareRouter([SimpleNamespace(binding='b',kind='CLOUD',model=None)])
 a=Agent(foundation_agent_model(r,lambda b:cloud,object()))
 @a.tool_plain
 def search(query:str)->str:return 'fresh'
 assert a.run_sync('weather').output=='done'
 assert r.phases==[None,None]


def test_model_adapter_does_not_reinterpret_tool_followup_semantics():
 from ai_foundation.routed_agent_model import _messages
 from pydantic_ai.messages import ModelRequest,ToolReturnPart
 history=[ModelRequest(parts=[ToolReturnPart(tool_name='search',content='observed',tool_call_id='c1')])]
 rows=_messages(history)
 assert rows==[{'role':'tool','tool_call_id':'c1','content':'observed'}]
 # The adapter's responsibility ends at lossless provider-neutral serialization;
 # Pydantic AI, not Foundation phase logic, decides subsequent tool validity.


class PrivacyAwareRouter:
 def __init__(self):
  self.settings = None; self.requests = []
 def choose(self, function, local_required=False, exclude=()):
  self.requests.append(local_required)
  binding, kind = ('local:approved', 'LOCAL') if local_required else ('cloud:normal', 'CLOUD')
  if binding in exclude: return SimpleNamespace(binding=None)
  return SimpleNamespace(binding=binding, kind=kind, model='synthetic', execution_slot=None)


def test_agent_tool_result_structured_pii_switches_followup_to_local():
 class LocalModel:
  def __init__(self): self.payloads = []
  def chat_payload(self, payload, model=None):
   self.payloads.append(payload)
   return {'model': 'synthetic', 'choices': [{'message': {'content': 'local answer'}}]}
 cloud = Cloud({'model': 'x', 'choices': [{'message': {'tool_calls': [
  {'id': 'c1', 'type': 'function', 'function': {'name': 'search', 'arguments': '{"query":"now"}'}}
 ]}}]})
 router = PrivacyAwareRouter(); local = LocalModel()
 model = foundation_agent_model(router, lambda _: cloud, local)
 agent = Agent(model)
 @agent.tool_plain
 def search(query: str) -> str: return 'Contact person@example.com'
 assert agent.run_sync('weather').output == 'local answer'
 assert router.requests == [False, True]
 assert cloud.i == 1
 assert local.payloads[0]['messages'][-1]['role'] == 'tool'


def test_agent_direct_structured_private_input_never_constructs_cloud():
 router = PrivacyAwareRouter(); constructed = []
 class LocalModel:
  def chat_payload(self, payload, model=None):
   return {'model': 'synthetic', 'choices': [{'message': {'content': 'local answer'}}]}
 agent = Agent(foundation_agent_model(router, lambda b: constructed.append(b), LocalModel()))
 assert agent.run_sync('Call 090-1234-5678').output == 'local answer'
 assert router.requests == [True] and not constructed


def test_terminal_model_failure_is_typed_sanitized_and_never_retried_forever():
    class FailedCloud:
        def invoke_for_function(self, binding, payload, function):
            raise TimeoutError("PRIVATE_ACCESS_TOKEN_AND_PROMPT_MUST_NOT_LEAK")
    router = Router([SimpleNamespace(binding='one', kind='CLOUD', model=None)])
    model = foundation_agent_model(router, lambda _: FailedCloud(), object())
    with pytest.raises(AgentRouteUnavailable) as caught:
        Agent(model).run_sync('synthetic request')
    failure = caught.value
    assert failure.phase == 'initial'
    assert failure.reason_code == 'MODEL_TIMEOUT'
    assert failure.attempts == 1
    assert str(failure) == 'no eligible agent compute'
    assert 'PRIVATE_ACCESS_TOKEN' not in repr(failure)


def test_invalid_model_response_has_distinct_code_and_empty_pool_is_zero_attempts():
    router = Router([SimpleNamespace(binding='one', kind='CLOUD', model=None)])
    bad = Cloud({'model': 'synthetic', 'choices': [{'message': {}}]})
    with pytest.raises(AgentRouteUnavailable) as caught:
        Agent(foundation_agent_model(router, lambda _: bad, object())).run_sync('synthetic')
    assert (caught.value.reason_code, caught.value.attempts) == ('MODEL_RESPONSE_INVALID', 1)
    with pytest.raises(AgentRouteUnavailable) as empty:
        Agent(foundation_agent_model(Router([]), lambda _: None, object())).run_sync('synthetic')
    assert (empty.value.reason_code, empty.value.attempts) == ('NO_ELIGIBLE_ROUTE', 0)


def test_quota_exhausted_route_fails_over_to_next_free_route():
    class QuotaExhausted(Exception):
        status = 429

    class FirstQuotaThenRecover:
        def __init__(self):
            self.calls = []

        def invoke_for_function(self, b, payload, fn):
            self.calls.append(b)
            if b == 'first':
                raise QuotaExhausted('quota exhausted')
            return json.dumps({'model': b, 'choices': [
                {'message': {'content': 'served-by-second'},
                 'finish_reason': 'stop'}]})

    class RecordingRouter(Router):
        def __init__(self, routes):
            super().__init__(routes)
            self.runtime = []
            self.excludes = []

        def choose(self, function, exclude=()):
            self.excludes.append(set(exclude))
            return super().choose(function, exclude=exclude)

        def record_runtime(self, function, binding, success, latency_ms):
            self.runtime.append((binding, success))

    routes = [SimpleNamespace(binding='first', kind='CLOUD', model=None),
              SimpleNamespace(binding='second', kind='CLOUD', model=None)]
    router = RecordingRouter(routes)
    cloud = FirstQuotaThenRecover()
    model = foundation_agent_model(router, lambda b: cloud, object())
    assert Agent(model).run_sync('hello').output == 'served-by-second'
    assert cloud.calls == ['first', 'second']
    assert router.excludes[0] == set()
    assert router.excludes[1] == {'first'}
    assert router.runtime[0] == ('first', False)
    assert router.runtime[-1] == ('second', True)
