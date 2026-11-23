"""Capability-aware Vision backend selection; no model or product semantics."""
from __future__ import annotations
from .routing_capabilities import supports

class RoutedVisionBackend:
    name="foundation-vision-route"
    def __init__(self,router,local_factory,cloud_factory):
        self.router=router;self.local_factory=local_factory;self.cloud_factory=cloud_factory
    def analyze(self,paths,task,*,local_required=False,prefer_local=False):
        excluded=set();last=None
        while True:
            route=self.router.choose("VISION",local_required=local_required,prefer_local=prefer_local,exclude=excluded)
            if not route.binding:break
            try:
                backend=self.local_factory(route) if route.kind=="LOCAL" else self.cloud_factory(route)
                return backend.analyze(paths,task)
            except Exception as exc:
                last=exc;excluded.add(route.binding)
                if local_required and route.kind!="LOCAL":break
        if last is not None:raise RuntimeError("VISION routes exhausted") from last
        raise RuntimeError("VISION unavailable")
