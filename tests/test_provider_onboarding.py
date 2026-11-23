import pytest
from ai_foundation.provider_onboarding import ProviderOnboarding,ProbeResult,detect_provider
from ai_foundation.provider_registry import SQLiteProviderRegistry

class Store:
 def __init__(self): self.d={}
 def save(self,b,s): self.d[b]=s
 def delete(self,b): return self.d.pop(b,None) is not None
class Probe:
 def __init__(self,result): self.result=result; self.hint=None
 def probe(self,secret,provider_hint=None): self.hint=provider_hint; return self.result

def test_detects_known_key_format_without_persisting_raw_key(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite'); s=Store(); p=Probe(ProbeResult('GROQ','ONLINE',80,'20m',60,'10d'))
 key='gsk_'+'A'*24; b=ProviderOnboarding(r,s,p).add(key)
 assert p.hint=='GROQ' and s.d[b]==key and key not in repr(r.cards())

def test_unknown_key_requires_provider_when_probe_cannot_identify(tmp_path):
 with pytest.raises(ValueError,match='provider selection'):
  ProviderOnboarding(SQLiteProviderRegistry(tmp_path/'p.sqlite'),Store(),Probe(ProbeResult(None,'ONLINE',80,None,60,None))).add('opaque-secret')

def test_free_provider_can_register_when_quota_is_not_machine_readable(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite'); s=Store()
 b=ProviderOnboarding(r,s,Probe(ProbeResult('GEMINI','ONLINE'))).add('AIza'+'A'*24)
 c=r.credential(b)
 assert b in s.d and c['provider']=='GEMINI' and c['short_remaining'] is None and c['long_remaining'] is None

def test_failed_registry_write_rolls_back_keychain_secret():
 class Broken:
  def upsert(self,*a,**k): raise RuntimeError('db')
 s=Store()
 with pytest.raises(RuntimeError): ProviderOnboarding(Broken(),s,Probe(ProbeResult('GROQ','ONLINE',80,None,60,None))).add('gsk_'+'A'*24)
 assert not s.d
def test_detects_nvidia_key_family():
 assert detect_provider('nvapi-'+'A'*24)=='NVIDIA'

def test_rate_limited_credential_is_registered_but_not_online(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite');s=Store();p=Probe(ProbeResult('GROQ','RATE_LIMITED',reason='HTTP 429'))
 b=ProviderOnboarding(r,s,p).add('gsk_'+'A'*24)
 assert r.credential(b)['health']=='RATE_LIMITED'
def test_detects_github_fine_grained_token_family():
 assert detect_provider('github_pat_'+'A'*40)=='GITHUB'
