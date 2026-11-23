from ai_foundation.provider_registry import SQLiteProviderRegistry
from ai_foundation.provider_observer import ProviderResponseObserver

def reg(tmp_path,provider='GROQ'):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite'); r.upsert('b',provider,short_remaining=99,long_remaining=99); return r

def test_success_response_updates_real_activity_and_quota(tmp_path):
 r=reg(tmp_path); o=ProviderResponseObserver(r)
 x=o.observe('b','GROQ',200,{'x-ratelimit-limit-tokens':'100','x-ratelimit-remaining-tokens':'20','x-ratelimit-reset-tokens':'3s','x-ratelimit-limit-requests':'100','x-ratelimit-remaining-requests':'70','x-ratelimit-reset-requests':'1h'})
 c=r.credential('b'); assert x.quota_seen and c['active'] and c['short_remaining']==20 and c['long_remaining']==70
 o.finish('b'); assert not r.credential('b')['active']

def test_429_marks_rate_limited_without_erasing_last_known_quota(tmp_path):
 r=reg(tmp_path); ProviderResponseObserver(r).observe('b','GROQ',429,{})
 c=r.credential('b'); assert c['health']=='RATE_LIMITED' and c['reason']=='HTTP 429' and c['short_remaining']==99

def test_auth_and_server_failures_become_health_state(tmp_path):
 r=reg(tmp_path); o=ProviderResponseObserver(r)
 o.observe('b','GROQ',401,{}); assert r.credential('b')['health']=='CREDENTIAL_ERROR'
 o.observe('b','GROQ',503,{}); assert r.credential('b')['health']=='DOWN'
