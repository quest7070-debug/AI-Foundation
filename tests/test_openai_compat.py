import json,threading,urllib.request
from ai_foundation.operator_server import OperatorApplication
from ai_foundation.openai_compat import OpenAICompat
from ai_foundation.operator_server import serve
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.guard import GuardCore
from ai_foundation.core import GuardState
from ai_foundation.productization import FoundationConfig

class Infer:
 def run(self,plan,canon,function='CHAT'):
  assert 'user: hello' in plan.text and canon.revision=='openai-compat'
  return type('O',(),{'status':'VERIFIED_COMPLETE','result':'world','route_binding':'local:test'})()

def test_openai_compat_routes_through_foundation_inference(tmp_path):
 app=OperatorApplication(FoundationConfig(str(tmp_path)),OperatorActions(GuardCore(GuardState())),inference=Infer())
 srv=serve(app);threading.Thread(target=srv.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{srv.server_port}'
 try:
  models=json.load(urllib.request.urlopen(base+'/v1/models'));assert [x['id'] for x in models['data']]==['foundation-auto','foundation-search','foundation-code','foundation-data','foundation-files','foundation-vision']
  body=json.dumps({'model':'foundation-auto','messages':[{'role':'user','content':'hello'}]}).encode()
  req=urllib.request.Request(base+'/v1/chat/completions',data=body,method='POST',headers={'Content-Type':'application/json','X-Foundation-CSRF':app.csrf_token})
  row=json.load(urllib.request.urlopen(req));assert row['choices'][0]['message']['content']=='world'
 finally:srv.shutdown();srv.server_close()

def test_openai_compat_accepts_stream_flag(tmp_path):
 app=OperatorApplication(FoundationConfig(str(tmp_path)),OperatorActions(GuardCore(GuardState())),inference=Infer());srv=serve(app);threading.Thread(target=srv.serve_forever,daemon=True).start()
 try:
  body=json.dumps({'stream':True,'messages':[{'role':'user','content':'hello'}]}).encode();req=urllib.request.Request(f'http://127.0.0.1:{srv.server_port}/v1/chat/completions',data=body,method='POST',headers={'X-Foundation-CSRF':app.csrf_token})
  r=urllib.request.urlopen(req); assert r.status==200; assert r.headers.get_content_type()=='text/event-stream'; data=r.read().decode(); assert 'chat.completion.chunk' in data and 'world' in data and 'data: [DONE]' in data
 finally:srv.shutdown();srv.server_close()


def test_openai_compat_accepts_production_callable_inference(tmp_path):
 class CallableInfer:
  def __call__(self,receipt):
   return type('O',(),{'status':'VERIFIED_COMPLETE','result':'callable-ok','route_binding':'local:test'})()
 # Production passes a callable task boundary; compatibility must not silently disable it.
 app=OperatorApplication(FoundationConfig(str(tmp_path)),OperatorActions(GuardCore(GuardState())),inference=CallableInfer())
 assert app.openai is not None


def test_response_model_reports_actual_route_binding_not_requested_alias():
 r=OpenAICompat(Infer()).chat({'model':'foundation-auto','messages':[{'role':'user','content':'hello'}]})
 assert r['model']=='local:test'


def test_openai_compat_dispatches_host_selected_capability():
 seen=[]
 class RoutedInfer:
  def run(self,plan,canon,function='CHAT'):
   seen.append(function);return type('O',(),{'status':'VERIFIED_COMPLETE','result':'ok','route_binding':'route'})()
 r=OpenAICompat(RoutedInfer(),lambda text:'SEARCH').chat({'messages':[{'role':'user','content':'latest'}]})
 assert r['choices'][0]['message']['content']=='ok' and seen==['SEARCH']

def test_openai_compat_accepts_openai_text_content_array_but_rejects_unwired_attachment_types():
 seen=[]
 class I:
  def run(self,plan,canon,function='CHAT'):
   seen.append(plan.text);return type('O',(),{'status':'VERIFIED_COMPLETE','result':'ok','route_binding':'route'})()
 OpenAICompat(I()).chat({'messages':[{'role':'user','content':[{'type':'text','text':'hello'}]}]})
 assert 'user: hello' in seen[0]
 import pytest
 with pytest.raises(ValueError,match='unsupported attachment content'):
  OpenAICompat(I()).chat({'messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,AA=='}}]}]})

def test_trusted_capability_request_overrides_text_dispatch_without_prompt_inference():
 from ai_foundation.capability_request import CapabilityRequest
 seen=[]
 class I:
  def __call__(self,receipt):
   seen.append((receipt.function,receipt.capability_request))
   return type('O',(),{'status':'VERIFIED_COMPLETE','result':'ok','route_binding':'route'})()
 req=CapabilityRequest('DATA',data_operation='json_summary')
 OpenAICompat(I(),lambda _:'SEARCH').chat({'messages':[{'role':'user','content':'anything'}]},req)
 assert seen==[('DATA',req)]

def test_operator_converts_gateway_attachment_headers_to_trusted_request(tmp_path):
 seen=[]
 class CI:
  def __call__(self,receipt):
   seen.append(receipt.capability_request)
   return type('O',(),{'status':'VERIFIED_COMPLETE','result':'ok','route_binding':'route'})()
 app=OperatorApplication(FoundationConfig(str(tmp_path)),OperatorActions(GuardCore(GuardState())),inference=CI())
 srv=serve(app);threading.Thread(target=srv.serve_forever,daemon=True).start()
 try:
  body=json.dumps({'messages':[{'role':'user','content':'use file'}]}).encode()
  headers={'X-Foundation-CSRF':app.csrf_token,'X-Foundation-Owner':'u1','X-Foundation-Attachments':'[\"f1\"]'}
  req=urllib.request.Request(f'http://127.0.0.1:{srv.server_port}/v1/chat/completions',data=body,method='POST',headers=headers)
  assert json.load(urllib.request.urlopen(req))['choices'][0]['message']['content']=='ok'
  assert seen[0].owner_id=='u1' and seen[0].attachment_ids==('f1',)
 finally:srv.shutdown();srv.server_close()

def test_operator_accepts_signed_capability_context_without_attachments():
 import threading,http.client,json
 from ai_foundation.operator_server import OperatorApplication,serve
 seen=[]
 class O:
  def chat(self,payload,capability_request=None):seen.append(capability_request);return {'ok':True}
 app=OperatorApplication(type('C',(),{})(),object(),csrf_token='T');app.openai=O()
 app.capability_factory=lambda headers,payload,a: __import__('ai_foundation.capability_factory',fromlist=['build_daily_capability']).build_daily_capability(headers,payload,a,repo_roots={'p':'/trusted'})
 srv=serve(app);threading.Thread(target=srv.serve_forever,daemon=True).start()
 try:
  c=http.client.HTTPConnection('127.0.0.1',srv.server_port);body=b'{}';c.request('POST','/v1/chat/completions',body,{'X-Foundation-CSRF':'T','X-Foundation-Owner':'u','X-Foundation-Capability':'CODE','X-Foundation-Scope':'p','Content-Type':'application/json'});r=c.getresponse();r.read();assert r.status==200
  assert seen[0].capability=='CODE' and seen[0].repo_root=='/trusted'
 finally:srv.shutdown();srv.server_close()

def test_trusted_capability_uses_host_executor_not_plain_inference():
 from ai_foundation.capability_request import CapabilityRequest
 seen=[]
 class Plain:
  def run(self,*a,**k): raise AssertionError('trusted capability must not use plain inference')
 class Exec:
  def execute(self,request,text,run_id):
   seen.append((request.capability,text,run_id)); return 'scoped-result'
 c=__import__('ai_foundation.openai_compat',fromlist=['OpenAICompat']).OpenAICompat(Plain(),Exec())
 out=c.chat({'messages':[{'role':'user','content':'read note.txt'}]},CapabilityRequest('FILES',owner_id='u',file_read_root='/trusted'))
 assert out['choices'][0]['message']['content']=='scoped-result'
 assert out['model']=='foundation-files' and seen[0][0]=='FILES'


def test_operator_returns_explicit_404_for_missing_scoped_file():
 import threading,http.client
 class O:
  def chat(self,payload,capability_request=None): raise FileNotFoundError('file not found in bound scope: missing.txt')
 app=OperatorApplication(type('C',(),{})(),object(),csrf_token='T');app.openai=O()
 srv=serve(app);threading.Thread(target=srv.serve_forever,daemon=True).start()
 try:
  c=http.client.HTTPConnection('127.0.0.1',srv.server_port);body=b'{}';c.request('POST','/v1/chat/completions',body,{'X-Foundation-CSRF':'T','Content-Type':'application/json'});r=c.getresponse();data=r.read().decode();assert r.status==404 and 'missing.txt' in data
 finally:srv.shutdown();srv.server_close()


def test_trusted_chat_envelope_uses_plain_inference_not_capability_executor():
 from ai_foundation.capability_request import CapabilityRequest
 seen=[]
 class Plain:
  def run(self,plan,canon,function='CHAT'):
   seen.append(function); return type('O',(),{'status':'VERIFIED_COMPLETE','result':'title-ok','route_binding':'chat-route'})()
 class Exec:
  def execute(self,*a,**k): raise AssertionError('CHAT has no host capability executor')
 out=OpenAICompat(Plain(),Exec()).chat({'model':'foundation-auto','messages':[{'role':'user','content':'title'}]},CapabilityRequest('CHAT',owner_id='u'))
 assert out['choices'][0]['message']['content']=='title-ok' and seen==['CHAT']


def test_privacy_guard_input_excludes_assistant_and_system_text_but_keeps_all_user_turns():
 seen=[]
 class I:
  def run(self,plan,canon,function='CHAT'):
   seen.append(plan); return type('O',(),{'status':'VERIFIED_COMPLETE','result':'ok','route_binding':'route'})()
 c=OpenAICompat(I())
 c.chat({'messages':[{'role':'system','content':'personal files policy'},{'role':'user','content':'hello'},{'role':'assistant','content':'I cannot access your personal files'},{'role':'user','content':'why English?'}]})
 assert seen[-1].privacy_text=='hello\nwhy English?'
 c.chat({'messages':[{'role':'user','content':'my personal information'},{'role':'assistant','content':'ok'},{'role':'user','content':'continue'}]})
 assert seen[-1].privacy_text=='my personal information\ncontinue'


def test_callable_inference_receipt_preserves_user_only_privacy_text():
 seen=[]
 def inference(receipt):
  seen.append(receipt); return type('O',(),{'status':'VERIFIED_COMPLETE','result':'ok','route_binding':'route'})()
 OpenAICompat(inference).chat({'messages':[{'role':'assistant','content':'personal files'},{'role':'user','content':'why English?'}]})
 assert seen[0].privacy_text=='why English?'
 assert 'personal files' in seen[0].text

def test_trusted_vision_accepts_image_marker_but_ignores_client_url_as_authority(tmp_path):
 from ai_foundation.capability_request import CapabilityRequest,AttachmentGrant
 trusted=tmp_path/"trusted.png";trusted.write_bytes(b"\x89PNG\r\n\x1a\n"+b"0"*32)
 req=CapabilityRequest("VISION",owner_id="u",attachments=(AttachmentGrant("f","u",str(trusted.resolve())),),attachment_ids=("f",))
 seen=[]
 class Plain:
  def run(self,*a,**k):raise AssertionError("VISION must use capability executor")
 class Exec:
  def execute(self,request,text,run_id):
   seen.append((request.attachments[0].path,text));return "vision-ok"
 payload={"messages":[{"role":"user","content":[{"type":"text","text":"describe"},{"type":"image_url","image_url":{"url":"file:///etc/passwd"}}]}]}
 out=OpenAICompat(Plain(),Exec()).chat(payload,req)
 assert out["choices"][0]["message"]["content"]=="vision-ok"
 assert seen==[(str(trusted.resolve()),"describe")]

def test_image_marker_still_fails_without_resolved_trusted_vision_grant():
 import pytest
 from ai_foundation.capability_request import CapabilityRequest
 payload={"messages":[{"role":"user","content":[{"type":"image_url","image_url":{"url":"data:image/png;base64,AA=="}}]}]}
 with pytest.raises(ValueError,match="unsupported attachment content"):
  OpenAICompat(Infer()).chat(payload)
 with pytest.raises(ValueError,match="VISION requires trusted attachment"):
  CapabilityRequest("VISION",owner_id="u")

def test_chat_with_repo_grant_enters_auto_agent_not_direct_code_executor():
 from ai_foundation.capability_request import CapabilityRequest

 seen=[]

 class Plain:
  def run(self,*a,**k):
   raise AssertionError('auto-agent request must not use plain inference')

 class Exec:
  def execute(self,*a,**k):
   raise AssertionError('CHAT envelope must not directly dispatch CODE')

 def factory(request,run_id):
  seen.append((request.capability,request.repo_root,run_id))
  class Agent:
   def run(self,text,*,message_history=()):
    seen.append(('agent',text,message_history))
    return 'auto-code-ready'
  return Agent()

 c=OpenAICompat(Plain(),Exec(),factory)
 req=CapabilityRequest(
  'CHAT',
  owner_id='u',
  repo_root='/trusted/repo',
 )
 out=c.chat(
  {
   'model':'foundation-auto',
   'messages':[{
    'role':'user',
    'content':'Change the authorized repository file.',
   }],
  },
  req,
 )

 assert out['choices'][0]['message']['content']=='auto-code-ready'
 assert out['model']=='foundation-auto'
 assert seen[0][0]=='CHAT'
 assert seen[0][1]=='/trusted/repo'
 assert seen[1]==('agent','Change the authorized repository file.',())

def test_trusted_auto_chat_passes_prior_turns_as_structured_history():
    from ai_foundation.capability_request import CapabilityRequest
    from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart

    seen = []

    class Plain:
        def run(self,*a,**k):
            raise AssertionError("foundation-auto must use auto agent")

    class Auto:
        def run(self,text,*,message_history=()):
            seen.append((text,message_history))
            return "KITE-7391"

    def factory(request,run_id):
        return Auto()

    c = OpenAICompat(Plain(), auto_agent_factory=factory)

    out = c.chat(
        {
            "model":"foundation-auto",
            "messages":[
                {"role":"system","content":"client presentation context"},
                {"role":"user","content":"remember KITE-7391"},
                {"role":"assistant","content":"understood"},
                {"role":"user","content":"what was the code?"},
            ],
        },
        CapabilityRequest("CHAT",owner_id="u"),
    )

    assert out["choices"][0]["message"]["content"] == "KITE-7391"
    assert len(seen) == 1

    prompt, history = seen[0]
    assert prompt == "what was the code?"
    assert len(history) == 2

    assert isinstance(history[0],ModelRequest)
    assert len(history[0].parts) == 1
    assert isinstance(history[0].parts[0],UserPromptPart)
    assert history[0].parts[0].content == "remember KITE-7391"

    assert isinstance(history[1],ModelResponse)
    assert len(history[1].parts) == 1
    assert isinstance(history[1].parts[0],TextPart)
    assert history[1].parts[0].content == "understood"

    assert all(
        not any(
            getattr(part,"content",None) == "client presentation context"
            for part in message.parts
        )
        for message in history
    )

def test_trusted_auto_chat_preserves_prior_tool_history_as_native_parts():
    from ai_foundation.capability_request import CapabilityRequest
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        ToolCallPart,
        ToolReturnPart,
    )

    seen = []

    class Agent:
        def run(self, text, *, message_history=()):
            seen.append((text, message_history))
            return "done"

    compat = OpenAICompat(
        inference=lambda receipt: None,
        auto_agent_factory=lambda request, run: Agent(),
    )

    request = CapabilityRequest("CHAT", owner_id="u")

    result = compat.chat(
        {
            "messages": [
                {"role": "user", "content": "search for the value"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": "search",
                                "arguments": '{"q":"value"}',
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_123",
                    "content": "observed value",
                },
                {"role": "assistant", "content": "The value was observed."},
                {"role": "user", "content": "what did the tool observe?"},
            ]
        },
        capability_request=request,
    )

    assert result["choices"][0]["message"]["content"] == "done"

    current, history = seen[0]
    assert current == "what did the tool observe?"
    assert len(history) == 4

    assert isinstance(history[0], ModelRequest)
    assert history[0].parts[0].content == "search for the value"

    assert isinstance(history[1], ModelResponse)
    call = history[1].parts[0]
    assert isinstance(call, ToolCallPart)
    assert call.tool_name == "search"
    assert call.tool_call_id == "call_123"
    assert call.args_as_json_str() == '{"q":"value"}'

    assert isinstance(history[2], ModelRequest)
    returned = history[2].parts[0]
    assert isinstance(returned, ToolReturnPart)
    assert returned.tool_name == "search"
    assert returned.tool_call_id == "call_123"
    assert returned.content == "observed value"

    assert isinstance(history[3], ModelResponse)
    assert history[3].parts[0].content == "The value was observed."

def test_trusted_auto_chat_preserves_text_content_arrays_in_structured_history():
    from ai_foundation.capability_request import CapabilityRequest
    from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart

    seen = []

    class Agent:
        def run(self, text, *, message_history=()):
            seen.append((text, message_history))
            return "done"

    compat = OpenAICompat(
        inference=lambda receipt: None,
        auto_agent_factory=lambda request, run: Agent(),
    )

    result = compat.chat(
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "first"},
                        {"type": "text", "text": "second"},
                    ],
                },
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "answer"},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "current"},
                        {"type": "text", "text": "question"},
                    ],
                },
            ]
        },
        capability_request=CapabilityRequest("CHAT", owner_id="u"),
    )

    assert result["choices"][0]["message"]["content"] == "done"

    current, history = seen[0]
    assert current == "current\nquestion"
    assert len(history) == 2

    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[0].parts[0], UserPromptPart)
    assert history[0].parts[0].content == "first\nsecond"

    assert isinstance(history[1], ModelResponse)
    assert isinstance(history[1].parts[0], TextPart)
    assert history[1].parts[0].content == "answer"

def test_openai_compat_traces_message_count_without_message_content():
    from ai_foundation.observability import InMemoryTraceSink, Tracer

    sink = InMemoryTraceSink()
    tracer = Tracer(sink)

    class Infer:
        def run(self, plan, canon, function):
            return type(
                "Out",
                (),
                {
                    "status": "VERIFIED_COMPLETE",
                    "result": "ok",
                    "route_binding": "test",
                },
            )()

    compat = OpenAICompat(Infer(), tracer=tracer)
    compat.chat(
        {
            "messages": [
                {"role": "user", "content": "SECRET-FIRST-TURN"},
                {"role": "assistant", "content": "SECRET-ASSISTANT-TURN"},
                {"role": "user", "content": "SECRET-CURRENT-TURN"},
            ]
        }
    )

    events = [e for e in sink.events if e.name == "openai_compat.request"]
    assert len(events) == 1
    assert events[0].attributes == {"message_count": "3"}

    serialized = repr(events[0])
    assert "SECRET-FIRST-TURN" not in serialized
    assert "SECRET-ASSISTANT-TURN" not in serialized
    assert "SECRET-CURRENT-TURN" not in serialized
