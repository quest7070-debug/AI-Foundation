from dataclasses import dataclass

@dataclass(frozen=True)
class HumanRoute:
 function:str; primary:str; standbys:tuple[str,...]; execution_path:tuple[str,...]=(); uses_llm_route:bool=True

@dataclass(frozen=True)
class SystemTelemetry:
 ready:bool; checks:tuple=(); services:tuple=(); backup:dict|None=None; update:dict|None=None; trace_present:bool=False

@dataclass(frozen=True)
class HumanView:
 state:str; severity_counts:tuple[int,int,int,int,int]=(0,0,0,0,0)
 notices:tuple=(); tasks:tuple=(); providers:tuple=(); routes:tuple[HumanRoute,...]=(); credentials:tuple=(); local_compute:tuple=(); activity:tuple=(); telemetry:SystemTelemetry|None=None; development:dict|None=None; runtime_health:str='UNVERIFIED'

def from_snapshot(snapshot,*,notices=(),tasks=(),providers=(),routes=(),credentials=(),local_compute=(),activity=(),route_label=None,execution_paths=None,development=None):
 d=snapshot.as_dict(); attention=d.get('attention',()); state='READY'
 if d.get('update') and d['update'].get('transaction')=='APPLYING':state='RECOVERING'
 elif any(x.get('status')=='UNCERTAIN' for x in attention):state='UNCERTAIN'
 elif d.get('waiting_human'):state='WAITING_HUMAN'
 elif d.get('work',{}).get('RUNNING',0):state='RUNNING'
 elif any(x.get('status')=='FAILED' for x in attention):state='FAILED'
 # Service and preflight health is independent of persisted Work/Effect history.
 # Missing/untyped probes must never be reported as a healthy current runtime.
 services=d.get('services',())
 if type(services) not in (tuple,list): services=()
 if d.get('update') and type(d['update']) is dict and d['update'].get('transaction')=='APPLYING':
  runtime_health='RECOVERING'
 elif d.get('ready') is False or any(type(s) is dict and s.get('ok') is False for s in services):
  runtime_health='DEGRADED'
 elif (d.get('ready') is True and services
       and all(type(s) is dict and s.get('ok') is True for s in services)):
  runtime_health='READY'
 else:
  runtime_health='UNVERIFIED'
 label=route_label or (lambda b: str(b) if b else '—')
 paths=execution_paths or {}
 from .capability_topology import uses_llm_route
 human_routes=tuple(HumanRoute(r.function,label(r.primary),tuple(label(x) for x in r.standby),tuple(paths.get(r.function,())),uses_llm_route(r.function)) for r in routes)
 human_tasks=tuple(type(t)(t.job_id,t.text,t.created_at,t.status,t.result,t.verification,t.route_kind,t.evidence,label(t.route_binding) if t.route_binding else None) for t in tasks)
 telemetry=SystemTelemetry(d.get('ready') is True,tuple(d.get('checks',())),tuple(d.get('services',())),d.get('backup'),d.get('update'),bool(d.get('trace_present')))
 counts=tuple(sum(1 for n in notices if n.level==level) for level in range(1,6))
 return HumanView(state,counts,tuple(notices),human_tasks,tuple(providers),human_routes,tuple(credentials),tuple(local_compute),tuple(activity),telemetry,development,runtime_health)
