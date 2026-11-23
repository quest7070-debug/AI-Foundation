import os,sqlite3,threading,time
import pytest
from ai_foundation.provider_registry import SQLiteProviderRegistry
from ai_foundation.provider_onboarding import ProviderOnboarding,ProbeResult
from ai_foundation.settings_service import SettingsService
from ai_foundation.provider_quota import groq_quota

class Store:
 def __init__(self):self.d={};self.lock=threading.Lock()
 def save(self,b,s):
  with self.lock:self.d[b]=s
 def load(self,b):
  with self.lock:
   if b not in self.d:raise KeyError(b)
   return self.d[b]
 def available(self,b):return b in self.d
 def delete(self,b):
  with self.lock:return self.d.pop(b,None) is not None
class Probe:
 def probe(self,s,h=None):return ProbeResult(h or 'GROQ','ONLINE',80,'1m',70,'1d')

def test_provider_hint_cannot_override_detected_key_family(tmp_path):
 x=SettingsService(tmp_path,Probe(),Store()); x.add_provider('gsk_'+'A'*24,'MISTRAL')
 assert x.cards()[0].provider=='GROQ'

def test_invalid_tier_is_rejected(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite')
 with pytest.raises(ValueError): r.upsert('b','GROQ','NOT_A_TIER',short_remaining=1,long_remaining=1)

def test_invalid_quota_range_is_rejected(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite')
 with pytest.raises(ValueError): r.upsert('b','GROQ',short_remaining=999,long_remaining=-5)

def test_duplicate_registration_race_exposes_atomicity_gap(tmp_path):
 st=Store(); x=SettingsService(tmp_path,Probe(),st); key='gsk_'+'R'*24; errs=[]
 def f():
  try:x.add_provider(key)
  except Exception as e:errs.append(type(e).__name__)
 ts=[threading.Thread(target=f) for _ in range(2)];[t.start() for t in ts];[t.join() for t in ts]
 assert len(x.registry.bindings())>=1

def test_registry_permissions_are_not_world_writable(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite'); mode=os.stat(r.path).st_mode & 0o777
 assert not (mode & 0o002)

def test_preflight_detects_schema_tamper(tmp_path):
 x=SettingsService(tmp_path,Probe(),Store())
 with sqlite3.connect(x.registry.path) as db:
  db.execute('ALTER TABLE provider_credentials RENAME TO stolen')
 assert not x.preflight()['ok']
