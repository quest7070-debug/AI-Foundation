from ai_foundation.inference_service import GuardedInferenceService
from ai_foundation.core import *
from ai_foundation.guard import GuardCore
class Router:
 def __init__(self):self.calls=[]
 def choose(self,f,local_required=False,prefer_local=False,exclude=()):
  self.calls.append((local_required,prefer_local));binding='local:x' if local_required or prefer_local else 'cloud:x'
  if binding in exclude:return type('R',(),{'binding':None,'kind':None})()
  return type('R',(),{'binding':binding,'kind':'LOCAL' if local_required or prefer_local else 'CLOUD'})()
class Local:
 def __init__(self):self.calls=0
 def chat(self,x):self.calls+=1;return 'local:'+x
class Cloud:
 def __init__(self):self.calls=0
 def invoke(self,b,p):self.calls+=1;return 'cloud:'+p['messages'][0]['content']
def p(text):return TaskPlan('r','compute','llm',text=text,canon_revision='c',effect_id='e')
def test_secret_forces_local_and_never_builds_cloud():
 r=Router();l=Local();built=[];s=GuardedInferenceService(GuardCore(GuardState()),r,l,lambda b:built.append(b))
 o=s.run(p('password=secret'),CanonContract('x','c'));assert o.route_kind=='LOCAL' and o.route_binding=='local:x' and o.result.startswith('local:') and not built and r.calls[0][0]
def test_normal_cloud_route_executes():
 r=Router();l=Local();c=Cloud();s=GuardedInferenceService(GuardCore(GuardState()),r,l,lambda b:c)
 o=s.run(p('hello'),CanonContract('x','c'));assert o.route_kind=='CLOUD' and o.route_binding=='cloud:x' and o.result=='cloud:hello' and l.calls==0 and c.calls==1


def test_failed_compute_attempt_falls_through_to_next_eligible_route():
 class Routes:
  settings=None
  def choose(self,f,local_required=False,prefer_local=False,exclude=()):
   if 'cloud:x' not in exclude:return type('R',(),{'binding':'cloud:x','kind':'CLOUD'})()
   if 'local:x' not in exclude:return type('R',(),{'binding':'local:x','kind':'LOCAL'})()
   return type('R',(),{'binding':None,'kind':None})()
 class Broken:
  def invoke(self,b,p):raise RuntimeError('down')
 local=Local();svc=GuardedInferenceService(GuardCore(GuardState()),Routes(),local,lambda b:Broken())
 out=svc.run(p('hello'),CanonContract('x','c'))
 assert out.status=='VERIFIED_COMPLETE' and out.route_binding=='local:x' and out.result=='local:hello'

def test_local_failure_cooldown_skips_known_bad_binding_across_requests():
 from ai_foundation.local_health import LocalFailureCooldown
 now=[10.0]; health=LocalFailureCooldown(ttl=30,clock=lambda:now[0])
 class R:
  settings=None
  def choose(self,f,local_required=False,prefer_local=False,exclude=()):
   from ai_foundation.compute_routing import ComputeRoute
   return ComputeRoute('local:bad','LOCAL','bad') if 'local:bad' not in exclude else ComputeRoute('local:good','LOCAL','good')
 class L:
  def __init__(self):self.models=[]
  def chat(self,text,model=None):
   self.models.append(model)
   if model=='bad': raise RuntimeError('load failed')
   return 'ok'
 l=L(); svc=GuardedInferenceService(GuardCore(GuardState()),R(),l,local_health=health)
 assert svc.run(p('one'),CanonContract('x','c')).route_binding=='local:good'
 assert l.models==['bad','good']
 l.models.clear()
 assert svc.run(p('two'),CanonContract('x','c')).route_binding=='local:good'
 assert l.models==['good']
 now[0]=41.0; l.models.clear()
 assert svc.run(p('three'),CanonContract('x','c')).route_binding=='local:good'
 assert l.models==['good']

def test_cloud_http_failure_falls_through_once_per_binding_and_reaches_local():
 from ai_foundation.inference_service import GuardedInferenceService
 from ai_foundation.cloud_execution import ProviderHTTPError
 from ai_foundation.core import TaskPlan,CanonContract,Decision
 class Guard:
  def preflight(self,*a): return Decision.ALLOW
 class Route:
  def __init__(self,binding,kind,model=None):self.binding=binding;self.kind=kind;self.model=model
 class Router:
  settings=None
  order=(Route('a','CLOUD'),Route('b','CLOUD'),Route('local','LOCAL','m'))
  def choose(self,function,local_required=False,prefer_local=False,exclude=()):
   return next((x for x in self.order if x.binding not in exclude),Route(None,None))
 calls=[]
 class Cloud:
  def __init__(self,b):self.b=b
  def invoke_for_function(self,*a):calls.append(self.b);raise ProviderHTTPError(503)
  def extract_text(self,x):return x
 class Local:
  def chat(self,text,model=None):calls.append('local');return 'ok'
 s=GuardedInferenceService(Guard(),Router(),Local(),cloud_factory=lambda b:Cloud(b))
 p=TaskPlan('r','compute','llm',text='x',canon_revision='x',effect_id='e',privacy_text='x')
 out=s.run(p,CanonContract('x','x'))
 assert out.result=='ok' and calls==['a','b','local']


def test_local_failure_cooldown_persists_across_reconstruction(tmp_path):
 from ai_foundation.local_health import LocalFailureCooldown
 now=[100.0];path=tmp_path/'local-health.json'
 a=LocalFailureCooldown(ttl=60,clock=lambda:now[0],path=path);a.fail('local:broken')
 b=LocalFailureCooldown(ttl=60,clock=lambda:now[0],path=path);assert b.excluded()=={'local:broken'}
 now[0]=161.0;c=LocalFailureCooldown(ttl=60,clock=lambda:now[0],path=path);assert c.excluded()=={'local:broken'}
 c.success('local:broken');assert not c.excluded()
 assert path.stat().st_mode & 0o777 == 0o600

def test_selected_local_binding_dispatches_to_matching_backend():
 from ai_foundation.compute_routing import ComputeRoute
 from ai_foundation.openai_local_adapter import LocalExecutionDispatcher
 class R:
  settings=None
  def choose(self,*a,**k):return ComputeRoute('local:mainpc:general','LOCAL','runtime-model','general')
 class L:
  def __init__(self,name):self.name=name;self.models=[]
  def chat(self,text,model=None):self.models.append(model);return self.name
 m1=L('m1');pc=L('pc');svc=GuardedInferenceService(GuardCore(GuardState()),R(),LocalExecutionDispatcher(m1,(('local:mainpc',pc),)))
 out=svc.run(p('hello'),CanonContract('x','c'))
 assert out.result=='pc' and pc.models==['general'] and m1.models==[]


def test_resource_busy_does_not_poison_local_health_or_fall_through_to_cloud():
 from ai_foundation.host_compute_lease import HostComputeBusy
 from ai_foundation.local_health import LocalFailureCooldown
 class Busy:
  def chat(self,*a,**k):raise HostComputeBusy('HOST_COMPUTE_LEASE_BUSY')
 def forbidden_cloud(binding):raise AssertionError('no cloud fallback')
 health=LocalFailureCooldown()
 svc=GuardedInferenceService(GuardCore(GuardState()),Router(),Busy(),cloud_factory=forbidden_cloud,local_health=health)
 result=svc.run(p('password=secret'),CanonContract('x','c'))
 assert result.status=='LOCAL_RESOURCE_DEFERRED' and result.route_kind=='LOCAL'
 assert result.route_binding=='local:x' and result.result is None
 assert health.excluded()==set()


def test_misconfigured_router_cannot_disclose_guard_local_only_to_cloud():
    class BrokenRouter:
        settings = None
        def choose(self, *args, **kwargs):
            return type('Route', (), {'binding': 'cloud:x', 'kind': 'CLOUD'})()
    called = []
    def cloud_factory(binding):
        called.append(binding)
        raise AssertionError('never construct external provider')
    svc = GuardedInferenceService(GuardCore(GuardState()), BrokenRouter(), Local(),
                                  cloud_factory=cloud_factory)
    out = svc.run(p('contact person@example.com'), CanonContract('x', 'c'))
    assert out.status == 'NO_ELIGIBLE_COMPUTE'
    assert out.result is None and called == []


def test_interrupted_cloud_dispatch_must_reconcile_not_fall_back(tmp_path):
    from ai_foundation.compute_routing import ComputeRoute
    from ai_foundation.durable_inference import SQLiteInferenceAttemptStore

    attempts = SQLiteInferenceAttemptStore(tmp_path / 'attempts.db')
    attempts.get_or_begin('e', 'cloud:first')  # Existing process was interrupted.
    calls = []
    class Routes:
        settings = None
        def choose(self, function, *, local_required=False, prefer_local=False, exclude=()):
            if 'cloud:first' not in exclude:
                return ComputeRoute('cloud:first', 'CLOUD')
            return ComputeRoute('local:9b', 'LOCAL')
    class NeverCloud:
        def invoke(self, *a):
            calls.append('cloud')
            raise AssertionError('already dispatched')
    class NeverLocal:
        def chat(self, *a, **kw):
            calls.append('local')
            raise AssertionError('must not invent fallback')
    service = GuardedInferenceService(
        GuardCore(GuardState()), Routes(), NeverLocal(),
        cloud_factory=lambda binding: NeverCloud(), attempts=attempts)
    outcome = service.run(p('hello'), CanonContract('x', 'c'))
    assert outcome.status == 'UNCERTAIN_RECONCILE_REQUIRED'
    assert outcome.route_binding == 'cloud:first'
    assert outcome.result is None and calls == []
    assert attempts.get('e').status == 'DISPATCHING'



def test_local_chat_typeerror_is_not_retried_after_possible_model_dispatch():
 from ai_foundation.inference_port import LocalInferencePort, InferenceResultStore
 class BrokenLocal:
  def __init__(self): self.calls=0
  def chat(self,text,model=None):
   self.calls+=1
   raise TypeError("internal model failure after dispatch")
 local=BrokenLocal(); results=InferenceResultStore()
 port=LocalInferencePort(local,results,model="qwen3.5:9b")
 import pytest
 with pytest.raises(TypeError,match="internal model failure"):
  port.execute(p("hello"))
 assert local.calls==1
 assert results.get("e") is None


def test_local_chat_signature_selects_exactly_one_compatible_call():
 from ai_foundation.inference_port import LocalInferencePort, InferenceResultStore
 class Legacy:
  def __init__(self): self.calls=0
  def chat(self,text):
   self.calls+=1
   return "legacy:"+text
 class Dynamic:
  def __init__(self):self.calls=[]
  def chat(self,text,**kwargs):
   self.calls.append(kwargs)
   return "dynamic:"+text
 a=Legacy();b=Dynamic()
 one=InferenceResultStore();two=InferenceResultStore()
 LocalInferencePort(a,one,model="selected-slot").execute(p("hello"))
 LocalInferencePort(b,two,model="selected-slot").execute(p("hello"))
 assert a.calls==1 and one.get("e")=="legacy:hello"
 assert b.calls==[{"model":"selected-slot"}] and two.get("e")=="dynamic:hello"
