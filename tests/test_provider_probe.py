

def test_tavily_probe_proves_native_search_contract():
 import json
 from ai_foundation.provider_probe import LiveProviderProbe
 class Resp:
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def read(self,n):return json.dumps({'results':[{'url':'https://example.test'}]}).encode()
 seen={}
 def op(req,timeout):seen['url']=req.full_url;seen['auth']=req.get_header('Authorization');seen['body']=json.loads(req.data);return Resp()
 out=LiveProviderProbe(None,opener=op).probe('tvly-'+'A'*24,'TAVILY')
 assert out.health=='ONLINE' and seen['url']=='https://api.tavily.com/search' and seen['auth']=='Bearer tvly-'+'A'*24

def test_exa_native_search_probe_uses_x_api_key():
 import json
 from ai_foundation.provider_probe import LiveProviderProbe
 class Ctx:
  def __init__(self,b):self.b=b
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def read(self,n):return self.b
 seen={}
 def op(req,timeout):
  seen['url']=req.full_url;seen['key']=req.headers.get('X-api-key');seen['body']=json.loads(req.data);return Ctx(b'{"results":[]}')
 r=LiveProviderProbe(None,opener=op).probe('exa-secret','EXA')
 assert r.health=='ONLINE' and seen['url']=='https://api.exa.ai/search' and seen['key']=='exa-secret' and seen['body']['numResults']==1
