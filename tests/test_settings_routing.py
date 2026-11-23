from ai_foundation.settings_service import SettingsService
from ai_foundation.provider_onboarding import ProbeResult
class S:
 def save(self,*x):pass
 def load(self,b):return 'x'+b
 def available(self,b):return True
 def delete(self,b):return True
class P:
 def probe(self,*x):return ProbeResult('GROQ','ONLINE',80,'1m',70,'1d')
def test_settings_route_real_registry_metadata(tmp_path):
 x=SettingsService(tmp_path,P(),S());x.registry.upsert('a','GROQ','FREE','ONLINE',90,'x',80,'y',endpoint='https://x',model='m',protocol='openai-chat',capabilities=('CHAT','CODE'));x.registry.upsert('b','OPENROUTER','PAID','ONLINE',100,'x',100,'y',endpoint='https://x',model='m',protocol='openai-chat',capabilities=('CHAT','CODE'));r=x.optimize_routing();assert r.primary=='a' and r.standby==();assert x.choose_route()=='a'
def test_all_function_routes_persist(tmp_path):
 x=SettingsService(tmp_path,P(),S());x.registry.upsert('a','GROQ','FREE','ONLINE',90,'x',80,'y',endpoint='https://x',model='m',protocol='openai-chat',capabilities=('CHAT','CODE'));rows=x.optimize_all_routes();assert tuple(r.function for r in rows)==x.ROUTE_FUNCTIONS;by={r.function:r for r in x.routes()};assert by['CHAT'].primary=='a' and by['CODE'].primary is None ;assert by['SEARCH'].primary is None and by['DATA'].primary is None and by['FILES'].primary is None and by['PC_CONTROL'].primary is None
def test_route_label_never_needs_raw_binding(tmp_path):
 x=SettingsService(tmp_path,P(),S());x.registry.upsert('secret-binding-id','GROQ','FREE','ONLINE',90,'x',80,'y');assert x.route_label('secret-binding-id')=='Groq';assert x.route_label('gone')=='UNAVAILABLE'

def test_runtime_failover_quota_margin_and_recovery_without_reorder(tmp_path):
 x=SettingsService(tmp_path,P(),S());x.registry.upsert('a','GROQ','FREE','ONLINE',90,'s',80,'l',endpoint='https://x',model='m',protocol='openai-chat',capabilities=('CHAT','CODE'));x.registry.upsert('b','MISTRAL','FREE','ONLINE',70,'s',60,'l',endpoint='https://x',model='m',protocol='openai-chat',capabilities=('CHAT','CODE'));x.optimize_all_routes();assert x.route().primary=='a' and x.choose_route()=='a'
 # health registry skips primary immediately, but stored optimized order remains stable
 x.registry.observe('a',health='DOWN',active=False,reason='HTTP 503');assert x.choose_route()=='b';assert x.route().primary=='a'
 # recovery restores primary without a visual/policy reorder
 x.registry.observe('a',health='ONLINE',active=False,reason=None);assert x.choose_route()=='a';assert x.route().primary=='a'
 # safety margin: <=3% is exhausted for next task, so standby is selected
 x.registry.observe('a',health='ONLINE',short_remaining=3,long_remaining=80,active=False,reason=None);assert x.choose_route()=='b'
 # both unavailable/exhausted => fail closed
 x.registry.observe('b',health='RATE_LIMITED',active=False,reason='HTTP 429');assert x.choose_route() is None

def test_paid_candidate_remains_below_zero_paid_cost_candidates_at_policy_layer(tmp_path):
 from ai_foundation.routing import SQLiteRoutingPolicy
 r=SQLiteRoutingPolicy(tmp_path/'r.db')
 candidates=(
  {'binding':'cloud','tier':'FREE','health':'ONLINE','short_remaining':80,'long_remaining':80,'kind':'CLOUD'},
  {'binding':'local','tier':'LOCAL','health':'ONLINE','kind':'LOCAL'},
  {'binding':'paid','tier':'PAID','health':'ONLINE','short_remaining':100,'long_remaining':100,'kind':'CLOUD'},
 )
 route=r.optimize('GENERAL',candidates)
 assert route.primary in {'cloud','local'}
 assert route.standby[-1]=='paid'
 assert r.preferences('GENERAL')=={}


def test_restart_reconciles_stale_catalog_capabilities_before_routing(tmp_path):
 x=SettingsService(tmp_path,P(),S())
 x.registry.upsert('a','GROQ','FREE','ONLINE',90,'s',80,'l',
  endpoint='https://old',model='old',protocol='openai-chat',capabilities=('CHAT','CODE','DATA'))
 x.optimize_all_routes()
 assert x.route('DATA').primary is None
 y=SettingsService(tmp_path,P(),S())
 meta=y.registry.credential('a')
 assert meta['capabilities']==('CHAT','SEARCH','CODE','DATA')
 y.optimize_all_routes()
 assert y.route('DATA').primary is None and y.choose_route('DATA') is None
 assert meta['health']=='ONLINE' and meta['short_remaining']==90 and meta['long_remaining']==80

def test_routing_persists_more_than_three_eligible_candidates(tmp_path):
 x=SettingsService(tmp_path,P(),S())
 for i in range(5): x.registry.upsert(f'b{i}','GROQ','FREE','ONLINE',50,'s',50,'l',endpoint='https://x',model='m',protocol='openai-chat',capabilities=('CHAT',))
 r=x.optimize_routing('CHAT')
 assert len((r.primary,)+r.standby)==5

def test_cloud_candidates_precede_local_without_truncating(tmp_path):
 from ai_foundation.local_compute_registry import LocalComputeRegistry,LocalComputeCandidate
 local=LocalComputeRegistry(lambda:(LocalComputeCandidate('local:x',health='ONLINE',capabilities=('CHAT',)),))
 x=SettingsService(tmp_path,P(),S(),local_compute=local)
 for i in range(4): x.registry.upsert(f'b{i}','GROQ','FREE','ONLINE',50,'s',50,'l',endpoint='https://x',model='m',protocol='openai-chat',capabilities=('CHAT',))
 r=x.optimize_routing('CHAT')
 assert len((r.primary,)+r.standby)==5 and r.standby[-1]=='local:x'

def test_retired_github_is_not_presented_as_online_llm_capacity(tmp_path):
 x=SettingsService(tmp_path,P(),S())
 x.registry.upsert('gh','GITHUB','FREE','ONLINE')
 y=SettingsService(tmp_path,P(),S())
 m=y.registry.credential('gh')
 assert m['health']=='RETIRED' and 'retired' in m['reason'].lower()
 assert y.choose_route('CHAT') is None

def test_unknown_quota_is_eligible_but_known_exhaustion_is_not(tmp_path):
 x=SettingsService(tmp_path,P(),S())
 x.registry.upsert('unknown','NVIDIA','FREE','ONLINE',None,None,None,None,endpoint='https://x',model='m',protocol='openai-chat',capabilities=('CHAT',))
 x.optimize_routing('CHAT')
 assert x.route('CHAT').primary=='unknown'
 assert x.choose_route('CHAT')=='unknown'
 x.registry.observe('unknown',health='ONLINE',short_remaining=3,long_remaining=None,reason=None)
 assert x.choose_route('CHAT') is None

def test_search_and_data_only_advertise_real_groq_capacity(tmp_path):
 x=SettingsService(tmp_path,P(),S())
 for binding,provider,caps in (
  ('g','GROQ',('CHAT','SEARCH','CODE','DATA')),
  ('n','NVIDIA',('CHAT','CODE')),
  ('o','OPENROUTER',('CHAT','CODE')),
 ):
  x.registry.upsert(binding,provider,'FREE','ONLINE',None,None,None,None,endpoint='https://x',model='m',protocol='openai-chat',capabilities=caps)
 rows={r.function:r for r in x.optimize_all_routes()}
 assert rows['SEARCH'].primary=='g' and rows['SEARCH'].standby==()
 assert rows['DATA'].primary is None and rows['DATA'].standby==()
 assert set((rows['CHAT'].primary,)+rows['CHAT'].standby)=={'g','n','o'}

def test_provider_add_remove_republishes_visible_llm_routes(tmp_path):
 class DynamicProbe:
  def probe(self,key,provider=None):
   name=(provider or ('GROQ' if key.startswith('gsk_') else 'NVIDIA')).upper()
   return ProbeResult(name,'ONLINE',80,'1m',70,'1d')
 class Store:
  def __init__(self): self.d={}
  def save(self,b,v): self.d[b]=v
  def load(self,b): return self.d[b]
  def available(self,b): return b in self.d
  def delete(self,b): return self.d.pop(b,None) is not None
 st=Store(); x=SettingsService(tmp_path,DynamicProbe(),st)
 x.add_provider('gsk_'+'A'*24,'GROQ')
 before=x.routes(); chat=next(r for r in before if r.function=='CHAT')
 assert len((chat.primary,)+chat.standby)==1
 x.add_provider('nvapi-'+'B'*24,'NVIDIA')
 after=x.routes(); chat=next(r for r in after if r.function=='CHAT')
 labels=tuple(x.route_label(b) for b in (chat.primary,)+chat.standby)
 assert set(labels)=={'Groq','Nvidia'}
 n=next(b for b in x.registry.bindings() if x.registry.credential(b)['provider']=='NVIDIA')
 x.remove_provider(n)
 final=x.routes(); chat=next(r for r in final if r.function=='CHAT')
 assert tuple(x.route_label(b) for b in (chat.primary,)+chat.standby)==('Groq',)
 assert all(n not in ((r.primary,)+r.standby) for r in final)

def test_host_only_capabilities_never_persist_unused_llm_routes(tmp_path):
 x=SettingsService(tmp_path,P(),S())
 x.registry.upsert('g','GROQ','FREE','ONLINE',90,'s',80,'l',endpoint='https://x',model='m',protocol='openai-chat',capabilities=('CHAT','SEARCH','CODE','DATA'))
 rows={r.function:r for r in x.optimize_all_routes()}
 assert rows['CHAT'].primary=='g' and rows['SEARCH'].primary=='g'
 assert rows['CODE'].primary is None and rows['DATA'].primary is None
 assert x.choose_route('CODE') is None and x.choose_route('DATA') is None

def test_search_prefers_native_search_protocol_over_general_llm_capability(tmp_path):
 x=SettingsService(tmp_path,P(),S())
 x.registry.upsert('general','GROQ','FREE','ONLINE',99,'x',99,'y',endpoint='https://x',model='m',protocol='openai-chat',capabilities=('CHAT','SEARCH'))
 x.registry.upsert('native','EXA','FREE','ONLINE',None,None,None,None,endpoint='https://x',model='s',protocol='exa-search',capabilities=('SEARCH',))
 # Test secret adapter intentionally has no revocation signal; both registered rows are eligible.
 r=x.optimize_routing('SEARCH');assert r.primary=='native' and r.standby==('general',)

def test_choose_route_is_read_only_when_registry_was_mutated_outside_settings_boundary(tmp_path):
 class Probe: pass
 class Secrets:
  def available(self,b): return True
 class Local:
  def candidates(self): return ()
 svc=SettingsService(tmp_path,Probe(),secret_store=Secrets(),local_compute=Local())
 caps=('CHAT',)
 svc.registry.upsert('a','GROQ',health='ONLINE',capabilities=caps,endpoint='x',model='m',protocol='openai-chat')
 svc.registry.upsert('b','NVIDIA',health='DOWN',capabilities=caps,endpoint='x',model='m',protocol='openai-chat')
 svc.optimize_routing('CHAT')
 svc.registry.observe('b',health='ONLINE')
 assert svc.choose_route('CHAT')=='a'
 snap=svc.route('CHAT')
 assert 'b' not in ((snap.primary,)+snap.standby)

def test_refresh_provider_republishes_recovered_route_at_mutation_boundary(tmp_path):
 from ai_foundation.provider_onboarding import ProbeResult
 class Probe:
  def probe(self,*a): return ProbeResult('NVIDIA','ONLINE',None,None,None,None)
 class Secrets:
  def load(self,b): return 'secret'
  def available(self,b): return True
 class Local:
  def candidates(self): return ()
 svc=SettingsService(tmp_path,Probe(),secret_store=Secrets(),local_compute=Local())
 caps=('CHAT',)
 svc.registry.upsert('a','GROQ',health='ONLINE',capabilities=caps,endpoint='x',model='m',protocol='openai-chat')
 svc.registry.upsert('b','NVIDIA',health='DOWN',capabilities=caps,endpoint='x',model='m',protocol='openai-chat')
 svc.optimize_routing('CHAT')
 assert 'b' not in ((svc.route('CHAT').primary,)+svc.route('CHAT').standby)
 svc.refresh_provider('b')
 snap=svc.route('CHAT')
 assert 'b' in ((snap.primary,)+snap.standby)


def test_refresh_uses_current_probe_health_instead_of_stale_registry_health(tmp_path):
 from ai_foundation.provider_onboarding import ProbeResult
 class Probe:
  def probe(self,*a): return ProbeResult('GROQ','RATE_LIMITED',99.0,'1m',97.0,'1d',reason='HTTP 429')
 class Secrets:
  def load(self,b): return 'secret'
  def available(self,b): return True
 class Local:
  def candidates(self): return ()
 svc=SettingsService(tmp_path,Probe(),secret_store=Secrets(),local_compute=Local())
 svc.registry.upsert('g','GROQ',health='ONLINE',short_remaining=99,long_remaining=97,capabilities=('CHAT',),endpoint='x',model='m',protocol='openai-chat')
 assert svc.refresh_provider('g')['health']=='RATE_LIMITED'
 assert svc.registry.credential('g')['health']=='RATE_LIMITED'
