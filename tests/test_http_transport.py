import io,json
from urllib.error import HTTPError
import pytest
from ai_foundation.http_transport import UrllibCloudTransport
class Resp:
 def __init__(self,status=200,headers=None,body=b'{}'): self.status=status; self.headers=headers or {}; self.body=body
 def __enter__(self): return self
 def __exit__(self,*a): pass
 def read(self,n=-1): return self.body if n<0 else self.body[:n]

def test_groq_request_has_bearer_and_json_without_logging_secret():
 seen={}
 def op(req,timeout):
  seen.update(url=req.full_url,auth=req.get_header('Authorization'),user_agent=req.get_header('User-agent'),payload=json.loads(req.data),timeout=timeout); return Resp(headers={'x-ratelimit-limit-tokens':'10'})
 r=UrllibCloudTransport(opener=op,timeout=7).send('groq','SECRET',{'model':'x','messages':[]})
 assert seen=={'url':'https://api.groq.com/openai/v1/chat/completions','auth':'Bearer SECRET','user_agent':'AI-Foundation/1.0','payload':{'model':'x','messages':[]},'timeout':7}
 assert r.status==200

def test_http_error_is_returned_for_observer_classification():
 def op(req,timeout): raise HTTPError(req.full_url,429,'rate',{'Retry-After':'2'},io.BytesIO(b'limited'))
 r=UrllibCloudTransport(opener=op).send('MISTRAL','S',{})
 assert r.status==429 and r.body=='limited' and r.headers['Retry-After']=='2'

def test_unknown_provider_fails_before_network():
 with pytest.raises(ValueError,match='unsupported'): UrllibCloudTransport(opener=lambda *a:None).send('NOPE','S',{})

def test_response_size_is_bounded():
 class Resp:
  status=200;headers={}
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def read(self,n=-1):return b'x'*11
 import pytest
 with pytest.raises(ValueError,match='too large'):UrllibCloudTransport({'GROQ':'https://example.test'},opener=lambda *a,**k:Resp(),max_response_bytes=10).send('GROQ','s',{})
def test_redirect_handler_rejects_cross_origin():
 from ai_foundation.http_transport import _SameHostRedirect
 from urllib import request,error
 import pytest
 req=request.Request('https://a.test/x',headers={'Authorization':'Bearer SECRET'})
 with pytest.raises(error.HTTPError):_SameHostRedirect().redirect_request(req,None,302,'','', 'https://evil.test/y')

def test_gemini_uses_native_api_key_auth_and_translates_messages():
 class Resp:
  status=200; headers={}
  def __enter__(self): return self
  def __exit__(self,*a): pass
  def read(self,n): return b'{}'
 seen={}
 def op(req,timeout=None):
  seen['headers']={k.lower():v for k,v in req.header_items()};seen['body']=__import__('json').loads(req.data);return Resp()
 UrllibCloudTransport(opener=op).send('GEMINI','secret',{'model':'ignored','messages':[{'role':'user','content':'hello'}]})
 assert seen['headers']['x-goog-api-key']=='secret'
 assert 'authorization' not in seen['headers']
 assert seen['body']=={'contents':[{'role':'user','parts':[{'text':'hello'}]}]}


def test_gemini_translates_openai_tools_and_normalizes_function_call():
 seen={}
 class R(Resp):
  def __init__(self): super().__init__(body=json.dumps({'candidates':[{'content':{'parts':[{'functionCall':{'id':'c1','name':'search','args':{'q':'x'}}}]}}]}).encode())
 def op(req,timeout=None):seen['body']=json.loads(req.data);return R()
 out=UrllibCloudTransport(opener=op).send('GEMINI','secret',{'messages':[{'role':'system','content':'sys'},{'role':'user','content':'find x'}],'tools':[{'type':'function','function':{'name':'search','description':'Search','parameters':{'type':'object','properties':{'q':{'type':'string'}}}}}]})
 assert seen['body']['systemInstruction']['parts'][0]['text']=='sys'
 assert seen['body']['tools'][0]['functionDeclarations'][0]['name']=='search'
 msg=json.loads(out.body)['choices'][0]['message'];assert msg['tool_calls'][0]['function']=={'name':'search','arguments':'{\"q\":\"x\"}'}

def test_gemini_translates_tool_result_with_matching_call_id():
 seen={}
 def op(req,timeout=None):seen['body']=json.loads(req.data);return Resp(body=json.dumps({'candidates':[{'content':{'parts':[{'text':'done'}]}}]}).encode())
 payload={'messages':[{'role':'assistant','content':None,'tool_calls':[{'id':'c1','type':'function','function':{'name':'search','arguments':'{\"q\":\"x\"}'}}]},{'role':'tool','tool_call_id':'c1','content':'result'}],'tools':[]}
 out=UrllibCloudTransport(opener=op).send('GEMINI','secret',payload)
 assert seen['body']['contents'][1]['parts'][0]['functionResponse']=={'id':'c1','name':'search','response':{'output':'result'}}
 assert json.loads(out.body)['choices'][0]['message']['content']=='done'
