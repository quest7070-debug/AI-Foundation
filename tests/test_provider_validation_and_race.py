import threading,pytest
from ai_foundation.settings_service import SettingsService
from ai_foundation.provider_registry import SQLiteProviderRegistry
from ai_foundation.provider_onboarding import ProbeResult
class S:
 def __init__(self):self.d={}
 def save(self,b,s):self.d[b]=s
 def load(self,b):
  if b not in self.d:raise KeyError(b)
  return self.d[b]
 def available(self,b):return b in self.d
 def delete(self,b):return self.d.pop(b,None) is not None
class P:
 def probe(self,s,h=None):return ProbeResult(h or 'GROQ','ONLINE',80,'1m',70,'1d')
def test_tier_allowlist(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite')
 with pytest.raises(ValueError):r.upsert('b','GROQ','BOGUS',short_remaining=1,long_remaining=1)
@pytest.mark.parametrize('q',[-1,101,float('inf')])
def test_quota_percent_range(tmp_path,q):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite')
 with pytest.raises(ValueError):r.upsert('b','GROQ',short_remaining=q,long_remaining=1)
@pytest.mark.parametrize('invalid', [-1, 101, 10 ** 2000,
                                     float('nan'), float('inf'),
                                     float('-inf'), True, '100'])
def test_live_provider_quota_rejects_unsafe_telemetry_without_mutation(tmp_path, invalid):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite')
 r.upsert('a','GROQ',short_remaining=70,long_remaining=55,health='ONLINE')
 before=r.credential('a')
 for field in ('short_remaining','long_remaining'):
  with pytest.raises(ValueError,match='quota remaining'):
   r.observe('a',health='DOWN',**{field:invalid})
  assert r.credential('a') == before

def test_huge_integer_quota_rejected_on_registration_as_value_error(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite')
 with pytest.raises(ValueError,match='quota remaining'):
  r.upsert('a','GROQ',short_remaining=10 ** 2000)
 assert r.bindings()==()

@pytest.mark.parametrize('invalid', [0, 1, None, 'false', 'true'])
def test_registered_provider_activity_requires_explicit_boolean(tmp_path, invalid):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite')
 with pytest.raises(ValueError, match='provider activity must be boolean'):
  r.upsert('a','GROQ',active=invalid)
 assert r.bindings()==()
 r.upsert('a','GROQ',active=False)
 assert r.credential('a')['active'] is False
 r.upsert('a','GROQ',active=True)
 assert r.credential('a')['active'] is True


def test_live_provider_activity_must_be_boolean(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite')
 r.upsert('a','GROQ',short_remaining=70)
 with pytest.raises(ValueError,match='boolean'):
  r.observe('a',active='0')
 assert r.credential('a')['active'] is False
 assert r.observe('a',active=True,short_remaining=0) is True
 assert r.credential('a')['active'] is True
 assert r.credential('a')['short_remaining'] == 0

def test_duplicate_add_is_serialized(tmp_path):
 x=SettingsService(tmp_path,P(),S());key='gsk_'+'R'*24;errs=[]
 def f():
  try:x.add_provider(key)
  except ValueError as e:errs.append(str(e))
 ts=[threading.Thread(target=f) for _ in range(2)];[t.start() for t in ts];[t.join() for t in ts]
 assert len(x.registry.bindings())==1 and errs==['credential already registered']

def test_quota_nan_and_inf_rejected(tmp_path):
 import pytest
 from ai_foundation.provider_registry import SQLiteProviderRegistry
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite')
 for q in (float('nan'),float('inf'),float('-inf')):
  with pytest.raises(ValueError): r.upsert('b','GROQ','FREE','ONLINE',q,'x',50,'y')

def test_add_provider_rolls_back_credential_if_route_publication_fails(tmp_path,monkeypatch):
 st=S();x=SettingsService(tmp_path,P(),st)
 def fail(): raise RuntimeError('routing failed')
 monkeypatch.setattr(x,'optimize_all_routes',fail)
 with pytest.raises(RuntimeError,match='routing failed'):x.add_provider('gsk_'+'Z'*24)
 assert x.registry.bindings()==() and st.d=={}

def test_refresh_and_preference_change_serialize_with_provider_mutation(tmp_path):
 x=SettingsService(tmp_path,P(),S());x.add_provider('gsk_'+'Q'*24);b=x.registry.bindings()[0];errs=[]
 def a():
  try:
   for _ in range(20):x.refresh_provider(b)
  except Exception as e:errs.append(e)
 def c():
  try:
   for n in range(20):x.optimize_all_routes()
  except Exception as e:errs.append(e)
 ts=[threading.Thread(target=a),threading.Thread(target=c)];[t.start() for t in ts];[t.join() for t in ts]
 assert not errs and x.preflight()['ok'] and x.route('CHAT').primary==b


class RateLimitedProbe:
 def probe(self,s,h=None):return ProbeResult(h or 'GROQ','RATE_LIMITED',reason='HTTP 429')

def test_replace_preserves_runnable_metadata_and_route_eligibility(tmp_path):
 st=S();x=SettingsService(tmp_path,P(),st)
 x.registry.upsert('b','GROQ','FREE','ONLINE',80,'1m',70,'1d',endpoint='https://api.groq.com/openai/v1/chat/completions',model='openai/gpt-oss-20b',auth_style='bearer',protocol='openai-chat',capabilities=('CHAT','SEARCH','CODE','DATA'))
 st.save('b','old');x.optimize_all_routes();assert x.choose_route('CHAT')=='b'
 x.replace_provider_credential('b','new')
 meta=x.registry.credential('b')
 assert (meta['endpoint'],meta['model'],meta['auth_style'],meta['protocol'])==('https://api.groq.com/openai/v1/chat/completions','openai/gpt-oss-20b','bearer','openai-chat')
 assert meta['capabilities']==('CHAT','SEARCH','CODE','DATA') and x.choose_route('CHAT')=='b' and st.load('b')=='new'

def test_replace_accepts_valid_rate_limited_credential_but_keeps_it_out_of_current_route(tmp_path):
 st=S();x=SettingsService(tmp_path,RateLimitedProbe(),st)
 x.registry.upsert('b','GROQ','FREE','ONLINE',80,'1m',70,'1d',endpoint='https://api.groq.com/openai/v1/chat/completions',model='openai/gpt-oss-20b',auth_style='bearer',protocol='openai-chat',capabilities=('CHAT',))
 st.save('b','old')
 out=x.replace_provider_credential('b','new')
 assert out['health']=='RATE_LIMITED' and x.registry.credential('b')['health']=='RATE_LIMITED'
 assert x.choose_route('CHAT') is None and st.load('b')=='new'
