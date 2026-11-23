import pytest
from ai_foundation.cloud_execution import ObservedCloudExecution,CloudResponse
from ai_foundation.provider_registry import SQLiteProviderRegistry
from ai_foundation.provider_observer import ProviderResponseObserver

class Store:
 def load(self,b): return 'raw-secret'
class Tx:
 def __init__(self,response=None,error=None): self.response=response; self.error=error; self.seen=None
 def send(self,p,s,payload):
  self.seen=(p,s,payload)
  if self.error: raise self.error
  return self.response

def setup(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite'); r.upsert('b','GROQ',short_remaining=99,long_remaining=99); return r

def test_real_execution_boundary_observes_response_and_never_passes_secret_to_registry(tmp_path):
 r=setup(tmp_path); tx=Tx(CloudResponse(200,{'x-ratelimit-limit-tokens':'100','x-ratelimit-remaining-tokens':'25','x-ratelimit-limit-requests':'100','x-ratelimit-remaining-requests':'75'},'ok'))
 x=ObservedCloudExecution(r,Store(),ProviderResponseObserver(r),tx)
 assert x.invoke('b',{'input':'hello'})=='ok'
 c=r.credential('b'); assert c['short_remaining']==25 and c['long_remaining']==75 and not c['active'] and c['health']=='ONLINE'
 assert tx.seen==('GROQ','raw-secret',{'input':'hello'})
 assert 'raw-secret' not in repr(c)

def test_http_failure_is_observed_then_raised_and_activity_cleared(tmp_path):
 r=setup(tmp_path); x=ObservedCloudExecution(r,Store(),ProviderResponseObserver(r),Tx(CloudResponse(429,{},'no')))
 with pytest.raises(RuntimeError,match='429'): x.invoke('b',{})
 c=r.credential('b'); assert c['health']=='RATE_LIMITED' and not c['active']

def test_transport_failure_marks_down_and_preserves_quota(tmp_path):
 r=setup(tmp_path); x=ObservedCloudExecution(r,Store(),ProviderResponseObserver(r),Tx(error=TimeoutError()))
 with pytest.raises(TimeoutError): x.invoke('b',{})
 c=r.credential('b'); assert c['health']=='DOWN' and c['short_remaining']==99 and not c['active']


def test_groq_function_payload_uses_verified_native_tools(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite')
 r.upsert('b','GROQ',endpoint='https://x',model='openai/gpt-oss-20b',protocol='openai-chat',capabilities=('CHAT','SEARCH','CODE','DATA'))
 tx=Tx(CloudResponse(200,{},'{"choices":[{"message":{"content":"ok"}}]}'))
 x=ObservedCloudExecution(r,Store(),ProviderResponseObserver(r),tx)
 body=x.invoke_for_function('b',{'messages':[{'role':'user','content':'q'}]},'SEARCH')
 assert x.extract_text(body)=='ok'
 assert tx.seen[2]['model']=='openai/gpt-oss-20b'
 assert tx.seen[2]['tools']==[{'type':'browser_search'}] and tx.seen[2]['tool_choice']=='required'
 x.invoke_for_function('b',{'messages':[{'role':'user','content':'q'}]},'DATA')
 assert tx.seen[2]['tools']==[{'type':'code_interpreter'}]

def test_extract_text_supports_gemini_and_cohere_shapes():
 import json
 assert ObservedCloudExecution.extract_text(json.dumps({'candidates':[{'content':{'parts':[{'text':'gemini'}]}}]}))=='gemini'
 assert ObservedCloudExecution.extract_text(json.dumps({'message':{'content':[{'type':'text','text':'cohere'}]}}))=='cohere'


def test_native_tavily_search_uses_search_contract_and_canonicalizes_evidence():
 import json
 from ai_foundation.cloud_execution import ObservedCloudExecution,CloudResponse
 class R:
  def credential(self,b):return {'provider':'TAVILY','protocol':'tavily-search','model':'tavily-search'}
  def observe(self,*a,**k):return True
 class S:
  def load(self,b):return 'secret'
 class O:
  def observe(self,*a,**k):pass
  def finish(self,*a):pass
 class T:
  def send(self,p,s,payload):self.seen=(p,s,payload);return CloudResponse(200,{},json.dumps({'results':[{'url':'https://example.test','title':'T','content':'C','score':0.9}]}))
 t=T();x=ObservedCloudExecution(R(),S(),O(),t)
 raw=x.invoke_for_function('b',{'messages':[{'role':'user','content':'formatting wrapper'}],'search_query':'current fact'},'SEARCH')
 assert t.seen==('TAVILY','secret',{'query':'current fact','max_results':5,'include_answer':False})
 out=json.loads(x.extract_text(raw));assert out['evidence'][0]['source']=='https://example.test'

def test_exa_search_is_native_search_capacity(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.db');r.upsert('e','EXA',endpoint='https://api.exa.ai/search',model='exa-search',auth_style='x-api-key',protocol='exa-search',capabilities=('SEARCH',))
 class S:
  def load(self,b):return 'secret'
 class O:
  def observe(self,*a):pass
  def finish(self,*a):pass
 class T:
  def send(self,p,s,payload):
   assert p=='EXA' and payload['query']=='fresh' and payload['numResults']==5
   return CloudResponse(200,{},'{"results":[{"title":"t","url":"https://x","text":"body","publishedDate":"2026-09-21"}]}')
 x=ObservedCloudExecution(r,S(),O(),T());body=x.invoke_for_function('e',{'messages':[{'role':'user','content':'fresh'}]},'SEARCH');text=x.extract_text(body)
 assert 'https://x' in text and 'body' in text and '2026-09-21' in text

def test_native_search_evidence_is_bounded_before_agent_context():
 import json
 body=json.dumps({'results':[{'url':'https://example.test','title':'T'*900,'text':'X'*9000} for _ in range(8)]})
 out=json.loads(ObservedCloudExecution.extract_text(body))
 assert len(out['evidence'])==5
 assert all(len(x['claim'])<=500 and len(x['excerpt'])<=1200 for x in out['evidence'])
