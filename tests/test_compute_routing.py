from ai_foundation.compute_routing import ComputeRouter
from ai_foundation.local_compute_registry import LocalComputeRegistry
class S:
 def __init__(self,x):self.x=x
 def choose_route(self,f,exclude=(),phase=None,local_candidates=None):return None if self.x in exclude else self.x
def reg(health='ONLINE'):return LocalComputeRegistry(lambda:[{'binding':'local:x','health':health,'capabilities':('CHAT',)}])
def test_cloud_default_local_fallback_and_preference():
 assert ComputeRouter(S('cloud:x'),reg()).choose().kind=='CLOUD'
 assert ComputeRouter(S(None),reg()).choose().kind=='LOCAL'
 assert ComputeRouter(S('cloud:x'),reg()).choose(prefer_local=True).kind=='LOCAL'
def test_local_required_never_falls_to_cloud():
 r=ComputeRouter(S('cloud:x'),reg('UNAVAILABLE')).choose(local_required=True);assert r.binding is None and r.kind is None


def test_persisted_local_primary_keeps_local_execution_kind():
 r=ComputeRouter(S('local:x'),reg()).choose()
 assert r.binding=='local:x' and r.kind=='LOCAL'


def test_workflow_route_does_not_become_search_just_because_local_can_generate_text():
 r=ComputeRouter(S(None),reg()).choose('RESEARCH')
 assert r.binding is None and r.kind is None

def test_vision_does_not_reuse_chat_only_local_candidate():
 r=ComputeRouter(S(None),reg()).choose("VISION")
 assert r.binding is None


def test_local_route_separates_model_identity_from_execution_slot():
 rr=LocalComputeRegistry(lambda:[{'binding':'local:x','health':'ONLINE','capabilities':('CHAT',),'model':'org/Qwen-model','slot':'local-general'}])
 route=ComputeRouter(S(None),rr).choose()
 assert route.kind=='LOCAL'
 assert route.model=='org/Qwen-model'
 assert route.execution_slot=='local-general'

def test_persisted_local_primary_preserves_execution_slot():
 rr=LocalComputeRegistry(lambda:[{'binding':'local:x','health':'ONLINE','capabilities':('CHAT',),'model':'org/Qwen-model','slot':'local-general'}])
 route=ComputeRouter(S('local:x'),rr).choose()
 assert (route.model,route.execution_slot)==('org/Qwen-model','local-general')

def test_vision_selects_explicit_local_candidate():
 vr=LocalComputeRegistry(lambda:[{"binding":"local:v","health":"ONLINE","capabilities":("VISION",)}])
 r=ComputeRouter(S(None),vr).choose("VISION")
 assert (r.binding,r.kind)==("local:v","LOCAL")


def test_public_strata_first_for_code_and_chat_but_never_private():
 from ai_foundation.local_compute_registry import LocalComputeCandidate
 class Inventory:
  def candidates(self):
   return (
    LocalComputeCandidate('local:mainpc-strata:code-agent',health='ONLINE',
      capabilities=('CODE','CHAT'),model='qwen3.8-flash-next-coder-iq1_m',
      slot='code-agent',same_host=False),
    LocalComputeCandidate('local:9b',health='ONLINE',
      capabilities=('CHAT','CODE'),model='pinned-m1',slot='general',same_host=True))
 router=ComputeRouter(S('free:admitted'),Inventory())
 assert router.choose('CHAT').binding=='free:admitted'
 assert router.choose('CHAT',strata_first=True).binding=='local:mainpc-strata:code-agent'
 assert router.choose('CODE',strata_first=True).binding=='local:mainpc-strata:code-agent'
 assert router.choose('CHAT',strata_first=True,local_required=True).binding=='local:9b'
 assert router.choose('CHAT',strata_first=True,prefer_local=True).binding=='local:9b'
 assert router.choose('DATA',strata_first=True).binding=='free:admitted' or router.choose('DATA',strata_first=True).binding is None
 assert router.choose('CHAT',strata_first=True,exclude=('local:mainpc-strata:code-agent',)).binding=='local:9b'


def test_strata_first_rejects_wrong_identity_offline_and_code_only():
 from ai_foundation.local_compute_registry import LocalComputeCandidate
 class Inventory:
  def __init__(self,health,capabilities,model):self.health=health;self.capabilities=capabilities;self.model=model
  def candidates(self):
   return (LocalComputeCandidate('local:mainpc-strata:code-agent',health=self.health,
     capabilities=self.capabilities,model=self.model,slot='code-agent',same_host=False),)
 for state,caps,identity in (
  ('UNAVAILABLE',('CHAT','CODE'),'qwen3.8-flash-next-coder-iq1_m'),
  ('ONLINE',('CODE',),'qwen3.8-flash-next-coder-iq1_m'),
  ('ONLINE',('CHAT','CODE'),'unverified-model'),
 ):
  router=ComputeRouter(S('free:admitted'),Inventory(state,caps,identity))
  assert router.choose('CHAT',strata_first=True).binding=='free:admitted'


def test_unreviewed_daily_chat_cannot_select_remote_strata_even_if_settings_lists_it():
 from ai_foundation.local_compute_registry import LocalComputeCandidate
 class Inventory:
  def candidates(self):
   return (LocalComputeCandidate('local:mainpc-strata:code-agent',health='ONLINE',
     capabilities=('CODE','CHAT'),model='qwen3.8-flash-next-coder-iq1_m',
     slot='code-agent',same_host=False),
     LocalComputeCandidate('local:9b',health='ONLINE',
       capabilities=('CHAT',),model='m1',same_host=True))
 class PreferStrata:
  def choose_route(self,capability,exclude=(),phase=None,local_candidates=None):
   return 'local:mainpc-strata:code-agent' if 'local:mainpc-strata:code-agent' not in exclude else None
 route=ComputeRouter(PreferStrata(),Inventory()).choose('CHAT')
 assert route.binding=='local:9b' and route.kind=='LOCAL'
 assert ComputeRouter(S('cloud:free'),Inventory()).choose('CHAT').binding=='cloud:free'
 assert ComputeRouter(PreferStrata(),Inventory()).choose('GENERAL').binding=='local:9b'
 assert ComputeRouter(PreferStrata(),Inventory()).choose('CHAT',strata_first=True).binding=='local:mainpc-strata:code-agent'


def test_public_strata_first_yields_to_shared_m1_9b_only_on_fresh_real_efficiency_evidence():
 import time
 from ai_foundation.local_compute_registry import LocalComputeCandidate
 class Inventory:
  def __init__(self,m1_online=True):self.m1_online=m1_online
  def candidates(self):
   return (
    LocalComputeCandidate('local:mainpc-strata:code-agent',health='ONLINE',
      capabilities=('CODE','CHAT'),model='qwen3.8-flash-next-coder-iq1_m',
      slot='code-agent',same_host=False),
    LocalComputeCandidate('local:ollama-shared9b:general',
      health='ONLINE' if self.m1_online else 'UNAVAILABLE',
      capabilities=('CHAT',),model='pinned-9b',slot='general',same_host=True))
 class Observed:
  def __init__(self, samples): self.samples=samples;self.calls=[]
  def runtime(self,binding,function='CHAT'):
   self.calls.append((binding,function))
   return self.samples.get(binding)
 class Config:
  def __init__(self,samples):self.routing=Observed(samples)
  def choose_route(self, function, exclude=(), phase=None, local_candidates=()):
   return 'free:approved'
 now=time.time()
 strong = {
  'local:mainpc-strata:code-agent': {'successes':4,'success_latency_ms':46000.0,'updated_at':now},
  'local:ollama-shared9b:general': {'successes':4,'success_latency_ms':12000.0,'updated_at':now},
 }
 settings=Config(strong)
 router=ComputeRouter(settings,Inventory())
 assert router.choose('CHAT',strata_first=True).binding=='local:ollama-shared9b:general'
 assert router.choose('CODE',strata_first=True).binding=='local:mainpc-strata:code-agent'
 assert router.choose('CHAT').binding=='free:approved'
 assert router.choose('CHAT',local_required=True).binding=='local:ollama-shared9b:general'
 assert settings.routing.calls==[
  ('local:mainpc-strata:code-agent','CHAT'),
  ('local:ollama-shared9b:general','CHAT')]
 assert ComputeRouter(Config(strong),Inventory(m1_online=False)).choose(
  'CHAT',strata_first=True).binding=='local:mainpc-strata:code-agent'
 incomplete={key:{**row,'successes':3} for key,row in strong.items()}
 assert ComputeRouter(Config(incomplete),Inventory()).choose(
  'CHAT',strata_first=True).binding=='local:mainpc-strata:code-agent'
 stale={key:{**row,'updated_at':now-8*86400} for key,row in strong.items()}
 assert ComputeRouter(Config(stale),Inventory()).choose(
  'CHAT',strata_first=True).binding=='local:mainpc-strata:code-agent'
 almost={**strong,'local:mainpc-strata:code-agent':{
   **strong['local:mainpc-strata:code-agent'],'success_latency_ms':18000.0}}
 assert ComputeRouter(Config(almost),Inventory()).choose(
  'CHAT',strata_first=True).binding=='local:mainpc-strata:code-agent'


def test_strata_efficiency_check_never_invents_evidence_from_invalid_telemetry():
 import time
 from ai_foundation.local_compute_registry import LocalComputeCandidate
 class Inventory:
  def candidates(self):
   return (
    LocalComputeCandidate('local:mainpc-strata:code-agent',health='ONLINE',
      capabilities=('CHAT','CODE'),model='qwen3.8-flash-next-coder-iq1_m',
      slot='code-agent',same_host=False),
    LocalComputeCandidate('local:ollama-shared9b:general',health='ONLINE',
      capabilities=('CHAT',),model='pinned-9b',slot='general',same_host=True))
 class Policy:
  def runtime(self,binding,function):
   if binding=='local:mainpc-strata:code-agent':
    return {'successes':7,'success_latency_ms':float('nan'),'updated_at':time.time()}
   return {'successes':7,'success_latency_ms':1000,'updated_at':time.time()}
 class Settings:
  routing=Policy()
  def choose_route(self,*args,**kwargs):return None
 assert ComputeRouter(Settings(),Inventory()).choose(
  'CHAT',strata_first=True).binding=='local:mainpc-strata:code-agent'


def test_optional_mainpc_absence_falls_to_online_m1_without_wake():
 from ai_foundation.local_compute_registry import LocalComputeCandidate
 class Inventory:
  def __init__(self): self.m1_up=True
  def candidates(self):
   return (LocalComputeCandidate('local:mainpc-strata:code-agent',
     health='UNAVAILABLE',capabilities=('CODE','CHAT'),
     model='qwen3.8-flash-next-coder-iq1_m',slot='code-agent',same_host=False),
    LocalComputeCandidate('local:ollama-shared9b:general',
     health='ONLINE' if self.m1_up else 'UNAVAILABLE',
     capabilities=('CHAT',),model='qwen3.5:9b',slot='general',same_host=True))
 class Approved:
  routing=None
  def choose_route(self, function, **kwargs):return 'free:admitted'
 inv=Inventory();route=ComputeRouter(Approved(),inv)
 assert route.choose('CHAT',strata_first=True).binding=='local:ollama-shared9b:general'
 assert route.choose('CHAT',strata_first=True,local_required=True).binding=='local:ollama-shared9b:general'
 assert route.choose('CODE',strata_first=True).binding=='free:admitted'
 inv.m1_up=False
 assert route.choose('CHAT',strata_first=True).binding=='free:admitted'
 assert route.choose('CHAT',local_required=True).binding is None


def test_in_request_failed_strata_uses_m1_before_cloud_without_second_remote_attempt():
 from ai_foundation.local_compute_registry import LocalComputeCandidate
 class Inventory:
  def candidates(self):
   return (LocalComputeCandidate('local:mainpc-strata:code-agent',
       health='ONLINE',capabilities=('CHAT','CODE'),
       model='qwen3.8-flash-next-coder-iq1_m',slot='code-agent',same_host=False),
     LocalComputeCandidate('local:ollama-shared9b:general',
       health='ONLINE',capabilities=('CHAT','CODE'),
       model='qwen3.5:9b',slot='general',same_host=True))
 class Approved:
  routing=None
  def choose_route(self,function,**kwargs):return 'free:admitted'
 router=ComputeRouter(Approved(),Inventory())
 assert router.choose('CHAT',strata_first=True).binding=='local:mainpc-strata:code-agent'
 assert router.choose('CHAT',strata_first=True,
     exclude=('local:mainpc-strata:code-agent',)).binding=='local:ollama-shared9b:general'
 assert router.choose('CODE',strata_first=True,
     exclude=('local:mainpc-strata:code-agent',)).binding=='local:ollama-shared9b:general'
