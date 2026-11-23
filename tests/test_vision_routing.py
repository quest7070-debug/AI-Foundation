import pytest
from ai_foundation.compute_routing import ComputeRouter
from ai_foundation.local_compute_registry import LocalComputeRegistry
from ai_foundation.vision_routing import RoutedVisionBackend
class S:
 def __init__(self,order):self.order=order or ()
 def choose_route(self,f,exclude=(),phase=None,local_candidates=None):
  return next((x for x in self.order if x not in exclude),None)
def reg(rows):return LocalComputeRegistry(lambda:rows)
class B:
 def __init__(self,name,fail=False):self.name=name;self.fail=fail
 def analyze(self,paths,task):
  if self.fail:raise RuntimeError("fail")
  return self.name+":"+task
def test_vision_uses_only_explicit_capability_and_can_choose_local():
 rows=[{"binding":"local:chat","health":"ONLINE","capabilities":("CHAT",)},{"binding":"local:vision","health":"ONLINE","capabilities":("VISION",)}]
 r=ComputeRouter(S(None),reg(rows))
 v=RoutedVisionBackend(r,lambda route:B(route.binding),lambda route:B(route.binding))
 assert v.analyze(("x",),"see")=="local:vision:see"
def test_vision_fallback_excludes_failed_route():
 rows=[{"binding":"local:v","health":"ONLINE","capabilities":("VISION",)}]
 r=ComputeRouter(S(["cloud:v"]),reg(rows))
 v=RoutedVisionBackend(r,lambda route:B(route.binding),lambda route:B(route.binding,fail=True))
 assert v.analyze(("x",),"see")=="local:v:see"
def test_local_required_never_uses_cloud():
 r=ComputeRouter(S(["cloud:v"]),reg([]));v=RoutedVisionBackend(r,lambda route:B(route.binding),lambda route:B(route.binding))
 with pytest.raises(RuntimeError,match="VISION unavailable"):v.analyze(("x",),"see",local_required=True)


def test_local_factory_receives_canonical_route_model_and_execution_slot():
 rows=[{
  "binding":"local:v",
  "health":"ONLINE",
  "capabilities":("VISION",),
  "model":"org/Vision-Model",
  "slot":"local-vision",
 }]
 r=ComputeRouter(S(None),reg(rows))
 seen={}
 def local_factory(route):
  seen["binding"]=route.binding
  seen["model"]=route.model
  seen["slot"]=route.execution_slot
  return B(route.binding)
 v=RoutedVisionBackend(r,local_factory,lambda route:B(route.binding))
 assert v.analyze(("x",),"see")=="local:v:see"
 assert seen=={
  "binding":"local:v",
  "model":"org/Vision-Model",
  "slot":"local-vision",
 }
