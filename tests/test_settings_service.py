from ai_foundation.settings_service import SettingsService
from ai_foundation.provider_onboarding import ProbeResult
class Store:
 def __init__(self): self.d={}
 def save(self,b,s): self.d[b]=s
 def delete(self,b): return self.d.pop(b,None) is not None
class Probe:
 def probe(self,s,h=None): return ProbeResult(h or 'GROQ','ONLINE',80,'1m',70,'1d')
def test_creates_real_registry_on_first_provider_add(tmp_path):
 s=SettingsService(tmp_path,Probe(),Store())
 assert not (tmp_path/'providers.sqlite').exists() is False
 out=s.add_provider('gsk_'+'A'*24)
 assert (tmp_path/'providers.sqlite').exists() and out['provider']=='GROQ' and out['credentials']==1

def test_refresh_and_replace_credential_follow_canonical_provider_controls(tmp_path):
 class ReadStore(Store):
  def load(self,b): return self.d[b]
  def available(self,b): return b in self.d
 store=ReadStore(); svc=SettingsService(tmp_path,Probe(),store)
 svc.add_provider('TEST_PROVIDER_TOKEN_A')
 binding=svc.registry.bindings()[0]
 refreshed=svc.refresh_provider(binding)
 assert refreshed['provider']=='GROQ' and refreshed['health']=='ONLINE'
 replaced=svc.replace_provider_credential(binding,'TEST_PROVIDER_TOKEN_B')
 assert replaced['provider']=='GROQ' and store.load(binding)=='TEST_PROVIDER_TOKEN_B'

def test_github_refresh_cannot_turn_retired_models_into_online_identity(tmp_path):
 class Probe:
  def probe(self,secret,provider_hint=None):
   from ai_foundation.provider_probe import ProbeResult
   return ProbeResult('GITHUB','ONLINE',reason='LLM capability not verified')
 class Store:
  def save(self,b,s):pass
  def load(self,b):return 'github_pat_abcdefghijklmnop'
  def available(self,b):return True
  def delete(self,b):return True
 svc=SettingsService(tmp_path,Probe(),Store())
 svc.registry.upsert('g','GITHUB','FREE','ONLINE')
 svc._reconcile_catalog_execution_metadata()
 assert svc.refresh_provider('g')['health']=='RETIRED'
 assert svc.registry.credential('g')['health']=='RETIRED'

def test_provider_add_remove_routes_persist_across_service_restart(tmp_path):
 class ReadStore(Store):
  def load(self,b): return self.d[b]
  def available(self,b): return b in self.d
 store=ReadStore(); a=SettingsService(tmp_path,Probe(),store)
 a.add_provider('gsk_'+'R'*24)
 binding=a.registry.bindings()[0]
 assert a.route('CHAT').primary==binding
 b=SettingsService(tmp_path,Probe(),store)
 assert b.registry.credential(binding)['health']=='ONLINE' and b.route('CHAT').primary==binding
 b.remove_provider(binding)
 assert binding not in b.registry.bindings()
 assert all(binding not in ((r.primary,)+r.standby) for r in b.routes())
 c=SettingsService(tmp_path,Probe(),store)
 assert binding not in c.registry.bindings()
 assert all(binding not in ((r.primary,)+r.standby) for r in c.routes())


def test_refresh_and_replaced_credential_survive_service_reconstruction(tmp_path):
    class ReadStore(Store):
        def load(self, binding):
            return self.d[binding]

        def available(self, binding):
            return binding in self.d

    store = ReadStore()
    first = SettingsService(tmp_path, Probe(), store)

    first.add_provider('TEST_PROVIDER_TOKEN_RESTART_A')
    binding = first.registry.bindings()[0]

    assert first.refresh_provider(binding)['health'] == 'ONLINE'
    assert first.replace_provider_credential(
        binding,
        'TEST_PROVIDER_TOKEN_RESTART_B',
    )['health'] == 'ONLINE'

    assert store.load(binding) == 'TEST_PROVIDER_TOKEN_RESTART_B'
    assert first.route('CHAT').primary == binding

    restarted = SettingsService(tmp_path, Probe(), store)

    assert store.load(binding) == 'TEST_PROVIDER_TOKEN_RESTART_B'
    assert restarted.registry.credential(binding)['health'] == 'ONLINE'
    assert restarted.route('CHAT').primary == binding
    assert restarted.choose_route('CHAT') == binding
