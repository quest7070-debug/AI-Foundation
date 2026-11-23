from urllib.error import HTTPError
import io
from ai_foundation.provider_probe import LiveProviderProbe
from ai_foundation.cloud_execution import CloudResponse
class T:
 def __init__(self,r):self.r=r;self.calls=[]
 def send(self,p,s,payload):self.calls.append((p,s,payload));return self.r
def H():return {'x-ratelimit-limit-tokens':'100','x-ratelimit-remaining-tokens':'80','x-ratelimit-reset-tokens':'7s','x-ratelimit-limit-requests':'1000','x-ratelimit-remaining-requests':'250','x-ratelimit-reset-requests':'1h'}
def test_groq_live_probe_minimal_request_and_quota():
 t=T(CloudResponse(200,H(),'{}'));r=LiveProviderProbe(t).probe('secret','GROQ'); assert r.health=='ONLINE' and (r.short_remaining,r.long_remaining)==(80,25); assert t.calls[0][2]['max_completion_tokens']==1
def test_groq_auth_failure_classified(): assert LiveProviderProbe(T(CloudResponse(401,{},''))).probe('x','GROQ').health=='CREDENTIAL_ERROR'
def test_groq_valid_key_stays_online_when_quota_headers_are_missing():
 r=LiveProviderProbe(T(CloudResponse(200,{},'{}'))).probe('x','GROQ'); assert r.health=='ONLINE' and r.short_remaining is None and r.long_remaining is None
def test_mistral_uses_its_own_live_path():
 t=T(CloudResponse(200,{'x-ratelimit-limit':'100','x-ratelimit-remaining':'75'},''));r=LiveProviderProbe(t).probe('x','MISTRAL');assert r.health=='ONLINE' and r.short_remaining==75 and t.calls[0][0]=='MISTRAL'
def test_openrouter_uses_its_own_live_path():
 t=T(CloudResponse(200,{},''));r=LiveProviderProbe(t).probe('x','OPENROUTER');assert r.health=='ONLINE' and t.calls[0][0]=='OPENROUTER'
def test_gemini_uses_x_goog_api_key_and_never_cloud_transport():
 seen={}
 class Resp:
  status=200
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def read(self,*a):return b'{}'
 def op(req,timeout):
  seen['url']=req.full_url;seen['key']=req.get_header('X-goog-api-key');seen['auth']=req.get_header('Authorization');return Resp()
 t=T(CloudResponse(500,{},''));r=LiveProviderProbe(t,opener=op).probe('gem-secret','GEMINI')
 assert r.health=='ONLINE' and 'generativelanguage.googleapis.com' in seen['url'] and seen['key']=='gem-secret' and seen['auth'] is None and not t.calls
def test_gemini_auth_failure_classified():
 def op(req,timeout):raise HTTPError(req.full_url,403,'bad',{},io.BytesIO(b'{}'))
 assert LiveProviderProbe(T(None),opener=op).probe('x','GEMINI').health=='CREDENTIAL_ERROR'
def test_nvidia_probe_authenticates_without_fixed_inference_model():
 seen={}
 class Resp:
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def read(self,*a):return b'{'
 def op(req,timeout):
  seen['url']=req.full_url;seen['auth']=req.get_header('Authorization');return Resp()
 t=T(CloudResponse(500,{},''));r=LiveProviderProbe(t,opener=op).probe('nvapi-test','NVIDIA')
 assert r.health=='ONLINE' and seen['url'].endswith('/v1/models') and seen['auth']=='Bearer nvapi-test' and not t.calls
def test_cohere_probe_authenticates_via_models_without_inference():
 seen={}
 class Resp:
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def read(self,*a):return b'{'
 def op(req,timeout):
  seen['url']=req.full_url;seen['auth']=req.get_header('Authorization');return Resp()
 t=T(CloudResponse(500,{},''));r=LiveProviderProbe(t,opener=op).probe('cohere-secret','COHERE')
 assert r.health=='ONLINE' and seen['url']=='https://api.cohere.com/v1/models' and seen['auth']=='Bearer cohere-secret' and not t.calls
def test_github_fine_grained_token_uses_identity_probe_not_llm_inference():
 seen={}
 class Resp:
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def read(self,*a):return b'{'
 def op(req,timeout):
  seen['url']=req.full_url;seen['auth']=req.get_header('Authorization');return Resp()
 t=T(CloudResponse(500,{},''));r=LiveProviderProbe(t,opener=op).probe('github_pat_example','GITHUB')
 assert r.health=='ONLINE' and seen['url']=='https://api.github.com/user' and seen['auth']=='Bearer github_pat_example' and not t.calls
