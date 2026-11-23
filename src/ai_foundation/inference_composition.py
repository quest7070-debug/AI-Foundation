"""Canonical host composition for provider/local inference shared by Operator and workers."""
from __future__ import annotations
from pathlib import Path
from .provider_probe import LiveProviderProbe
from .http_transport import UrllibCloudTransport
from .local_compute_registry import LocalComputeRegistry,CompositeLocalComputeRegistry
from .shared_ollama9b_adapter import SharedOllama9BDiscovery,SharedOllama9BExecution,PREFIX as OLLAMA9B_PREFIX
from .local_endpoint_config import load_local_endpoints
from .openai_local_adapter import LocalExecutionDispatcher
from .settings_service import SettingsService
from .compute_routing import ComputeRouter
from .inference_service import GuardedInferenceService
from .durable_inference import SQLiteInferenceAttemptStore
from .cloud_execution import ObservedCloudExecution
from .free_route_admission import SQLiteFreeRouteAdmission
from .provider_observer import ProviderResponseObserver
from .local_health import LocalFailureCooldown

class InferenceComposition:
 def __init__(self,service,settings,local_compute,transport):self.service=service;self.settings=settings;self.local_compute=local_compute;self.transport=transport

def _configured_endpoints(path):
 # The fixed same-host binding must have one discovery/execution identity.
 # Only explicit remote endpoints are composed with the one pinned M1 9B.
 # Former M1 llama-swap aliases are not a local-LLM fallback.
 return tuple(row for row in load_local_endpoints(path)
              if row[0] != OLLAMA9B_PREFIX
              and not row[0].startswith(OLLAMA9B_PREFIX + ':')
              and row[0] != 'local:llama-swap'
              and not row[0].startswith('local:llama-swap:'))

def build_inference_composition(*,root,config,guard,activity=None,storage_admission=None,transport=None,optimize=True,tracer=None):
 root=Path(root);transport=transport or UrllibCloudTransport()
 endpoints=_configured_endpoints(root/'local-compute'/'endpoints.json')
 # Public work may use remote reviewed specialists; local generative inference
 # on M1 is the ONE existing pinned 9B. Browser/free cloud providers remain
 # independent and unchanged. Missing/busy 9B means defer, never try 4B/GGUF.
 local=CompositeLocalComputeRegistry(*(x[1] for x in endpoints),LocalComputeRegistry(SharedOllama9BDiscovery()))
 local_execution=LocalExecutionDispatcher(None,((OLLAMA9B_PREFIX,SharedOllama9BExecution()),)+tuple((x[0],x[2]) for x in endpoints))
 free_route=SQLiteFreeRouteAdmission(root/'free-route-admission.sqlite',storage_admission=storage_admission)
 settings=SettingsService(root,LiveProviderProbe(transport),local_compute=local,storage_admission=storage_admission,free_route=free_route)
 if optimize:settings.optimize_all_routes()
 router=ComputeRouter(settings,local);observer=ProviderResponseObserver(settings.registry)
 def cloud_factory(binding):return ObservedCloudExecution(settings.registry,settings.secret_store,observer,transport,admission=free_route)
 service=GuardedInferenceService(guard,router,local_execution,cloud_factory=cloud_factory,activity=activity,attempts=SQLiteInferenceAttemptStore(root/config.inference_db,storage_admission=storage_admission),local_health=LocalFailureCooldown(path=root/'local-failure-cooldown.sqlite'),tracer=tracer)
 return InferenceComposition(service,settings,local,transport)
