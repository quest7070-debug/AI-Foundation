import sqlite3,pytest
from ai_foundation.settings_service import SettingsService
from ai_foundation.provider_onboarding import ProbeResult
class Store:
 def __init__(self):self.d={}
 def save(self,b,s):self.d[b]=s
 def load(self,b):
  if b not in self.d:raise KeyError(b)
  return self.d[b]
 def available(self,b):return b in self.d
 def delete(self,b):return self.d.pop(b,None) is not None
class Probe:
 def probe(self,s,h=None):return ProbeResult(h or 'GROQ','ONLINE',90,'1m',90,'1d')
def test_duplicate_key_rejected(tmp_path):
 x=SettingsService(tmp_path,Probe(),Store()); x.add_provider('gsk_'+'A'*24)
 with pytest.raises(ValueError,match='already registered'):x.add_provider('gsk_'+'A'*24)
 assert x.cards()[0].credentials==1
def test_remove_spans_secret_and_registry(tmp_path):
 st=Store();x=SettingsService(tmp_path,Probe(),st);x.add_provider('gsk_'+'B'*24); b=x.registry.bindings()[0]
 assert x.remove_provider(b)['removed'] and not x.registry.bindings() and b not in st.d
def test_failed_secret_delete_retains_registry(tmp_path):
 st=Store();x=SettingsService(tmp_path,Probe(),st);x.add_provider('gsk_'+'C'*24);b=x.registry.bindings()[0];st.d.clear()
 with pytest.raises(RuntimeError):x.remove_provider(b)
 assert x.registry.credential(b) is not None
def test_preflight_detects_missing_secret(tmp_path):
 st=Store();x=SettingsService(tmp_path,Probe(),st);x.add_provider('gsk_'+'D'*24);b=x.registry.bindings()[0];st.d.clear()
 p=x.preflight();assert not p['ok'] and p['missing_credentials']==(b,)
def test_integrity_detects_corrupt_db(tmp_path):
 x=SettingsService(tmp_path,Probe(),Store()); x.registry.path.write_bytes(b'not sqlite')
 assert not x.registry.integrity_check()['ok']

def test_reconcile_missing_credential_only_removes_stale_registry(tmp_path):
 from ai_foundation.settings_service import SettingsService
 class P: pass
 class Secrets:
  def __init__(self):self.present=set()
  def available(self,b):return b in self.present
 s=SettingsService(tmp_path,P(),Secrets());s.registry.upsert('b','GROQ','PAID','DOWN')
 r=s.reconcile_missing_credential('b');assert r['repaired'] and s.registry.credential('b') is None
 s.registry.upsert('c','GROQ','PAID','DOWN');s.secret_store.present.add('c')
 r=s.reconcile_missing_credential('c');assert not r['repaired'] and r['status']=='SECRET_PRESENT' and s.registry.credential('c')
