import html
import re
from datetime import datetime
from .human_components import action_form,button,panel,section,metric,section_header
from .human_styles import styles
from .human_surface import policy
from .provider_catalog import PROVIDER_NAMES
def _e(x):return html.escape(str(x if x is not None else '—'))
def _pct(x):return 'UNAVAILABLE' if x is None else f'{x:g}%'
def _observed(ts):
 if type(ts) not in (int,float) or not (0 < ts < 253402300800):return 'UNKNOWN'
 try:return datetime.fromtimestamp(ts).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
 except (OverflowError,OSError,ValueError):return 'UNKNOWN'
def _provider_panel(p,view):
 active=next((a.function for a in view.activity if a.provider.startswith(p.provider)),None);cls='compute-active' if active else '';now=f'<strong class="provider-active">IN USE · {_e(active)}</strong>' if active else ''
 limits=[]
 if p.short_remaining is not None:
  reset=f'<small>RESET · {_e(p.short_reset)}</small>' if p.short_reset else ''
  limits.append(f'<div class="limit"><span>SHORT LIMIT</span><strong>{_pct(p.short_remaining)}</strong>{reset}</div>')
 if p.long_remaining is not None:
  reset=f'<small>RESET · {_e(p.long_reset)}</small>' if p.long_reset else ''
  limits.append(f'<div class="limit"><span>LONG LIMIT</span><strong>{_pct(p.long_remaining)}</strong>{reset}</div>')
 limit_html=f'<div class="provider-limits">{"".join(limits)}</div>' if limits else ''
 note_label='ISSUE' if p.health in {'DOWN','RATE_LIMITED','CREDENTIAL_ERROR','RETIRED'} else 'NOTE'
 reason=f'<small class="provider-status provider-{note_label.lower()}">{note_label} · {_e(p.reason)}</small>' if p.reason else ''
 keys='KEY' if p.credentials==1 else 'KEYS'
 return f'<article class="ui-panel panel-capacity provider health-{_e(p.health).lower()} {cls}"><b class="provider-name">{_e(p.provider)}</b><span class="provider-meta">{_e(p.tier)} · {_e(p.health)} · {p.credentials} {keys}</span>{now}{limit_html}{reason}</article>'
def _local_panel(candidates,view,active_routes):
 candidates=tuple(candidates)
 if not candidates:return ''
 active=next((a.function for a in view.activity if a.kind=='LOCAL'),None);cls='compute-active' if 'LOCAL' in active_routes else '';now=f'<strong>USING NOW / {_e(active)}</strong>' if active else ''
 health='ONLINE' if any(c.health=='ONLINE' for c in candidates) else candidates[0].health
 rows=[]
 for c in candidates:
  name=c.model or 'LOCAL MODEL'
  slot=c.slot or 'UNASSIGNED SLOT'
  roles=' · '.join(c.roles or c.capabilities) or 'UNASSIGNED'
  characteristics=' · '.join(c.characteristics) or 'NO PROFILE'
  issue=f' · {_e(c.reason)}' if c.reason else ''
  # Keep the full dynamic inventory in the contract; the normal card projects only
  # identity + current role + health. Slot/profile are redundant implementation detail.
  short_name=name.split('/')[-1].removesuffix('-GGUF')
  role=roles if roles!='UNASSIGNED' else 'UNASSIGNED'
  rows.append(f'<small class="local-model"><b>{_e(short_name)}</b> · {_e(role)} · {_e(c.health)}{issue}</small>')
 return f'''<article class="ui-panel panel-capacity provider health-{_e(health).lower()} {cls}"><b class="provider-name">LOCAL COMPUTE</b><span class="provider-meta">{len(candidates)} MODELS · {_e(health)}</span>{now}{"".join(rows)}</article>'''
def _route_segment(label):
 paid=' / PAID' in label
 clean=label.replace(' / PAID','')
 suffix=' · PAID' if paid else ''
 cls='route-hop paid-hop' if paid else 'route-hop'
 return f'<span class="{cls}">{_e(clean)}{suffix}</span>'
def _route_panel(r,view):
 rows=[a for a in view.activity if a.function==r.function]; executing=next((a for a in rows if a.kind!='RESOLVING'),None); resolving=next((a for a in rows if a.kind=='RESOLVING'),None); active=executing.provider if executing else None;cls='route-active' if executing else '';now=f'<strong>USING NOW / {_e(active)}</strong>' if active else (f'<strong class="route-resolving">RESOLVING REQUEST</strong>' if resolving else '')
 chain=((r.primary,)+r.standbys) if r.uses_llm_route else ()
 llm_path='<span class="route-arrow"> → </span>'.join(_route_segment(x) for x in chain if x and x!='—')
 exec_path='<span class="route-arrow"> → </span>'.join(_route_segment(x) for x in r.execution_path)
 if exec_path and llm_path:
  path=exec_path+f'<span class="route-arrow"> → </span><span class="route-llm-inline">LLM ROUTE ({llm_path})</span>'
 elif llm_path:
  path=f'<span class="route-llm-inline">LLM ROUTE ({llm_path})</span>'
 else:
  path=exec_path or '<span>NOT AVAILABLE</span>'
 label={'DATA':'DATA ANALYSIS','PC_CONTROL':'PC CONTROL'}.get(r.function,r.function)
 note='<small>CODE-BASED CALCULATION / AGGREGATION</small>' if r.function=='DATA' else ''
 return f'<article class="ui-panel panel-route route {cls}"><b>{_e(label)}</b><div class="route-path">{path}</div>{note}{now}</article>'

_SHARED_9B_REASONS = frozenset({
 'PINNED_9B_NOT_VERIFIED', 'OTHER_LOCAL_MODEL_OR_BACKEND_RESIDENT',
 'CPU_PRESSURE', 'MEMORY_PRESSURE', 'RESOURCE_UNKNOWN',
 'SHARED_9B_STATE_UNVERIFIED',
})
def _shared9b_overview(candidates):
 # Same current discovery snapshot as SETTINGS; never infer running inference
 # from a scheduler, installed model name or successful source CI.
 rows=[c for c in candidates if getattr(c,'binding',None)=='local:ollama-shared9b:general']
 if len(rows)!=1:
  return 'UNVERIFIED','NO UNIQUE SAME-HOST SHARED-9B OBSERVATION'
 model=rows[0]
 if model.health=='ONLINE' and model.active is True and model.same_host is True:
  return 'DISCOVERED','CURRENT DISCOVERY ONLY · INFERENCE NOT VERIFIED'
 if model.health=='UNAVAILABLE' and model.active is False and model.same_host is True:
  reason=model.reason
  if type(reason) is str and reason in _SHARED_9B_REASONS:
   return 'UNAVAILABLE',reason+' · NO MODEL EVICTION'
 return 'UNVERIFIED','MODEL ADMISSION NOT PROVEN'


_STRATA_REASONS = frozenset({
 'HTTP_401','HTTP_403','HTTP_429','HTTP_500','HTTP_502',
 'HTTP_503','HTTP_504','TimeoutError','URLError',
 'ConnectionRefusedError','NO_AUTHORIZED_MODEL',
})
# The host did not answer at all: the PC sleeps when idle by design and the
# development lane wakes it on demand, so this is standby, not an outage.
# HTTP-class reasons mean the host answered and the service errored.
_STRATA_STANDBY_REASONS = frozenset({
 'TimeoutError','URLError','ConnectionRefusedError',
})
def _strata_overview(candidates):
 # Discovery is a cheap snapshot, not evidence of a model turn or a running
 # development worker. Only the exact approved remote CODE binding qualifies.
 rows=[c for c in candidates if getattr(c,'binding',None)==
       'local:mainpc-strata:code-agent']
 if len(rows)==1:
  c=rows[0]
  if (c.health=='ONLINE' and c.active is True and c.same_host is False
      and c.model=='qwen3.8-flash-next-coder-iq1_m'
      and 'CODE' in c.capabilities):
   return 'DISCOVERED','CURRENT CODE MODEL · NO ACTIVE JOB PROVEN'
 failures=[c for c in candidates if getattr(c,'binding',None)==
           'local:mainpc-strata']
 if len(failures)==1 and failures[0].health=='UNAVAILABLE':
  reason=failures[0].reason
  if type(reason) is str and reason in _STRATA_STANDBY_REASONS:
   return 'STANDBY',reason+' · WAKES ON DEMAND'
  if type(reason) is str and reason in _STRATA_REASONS:
   return 'UNAVAILABLE',reason+' · SERVICE ERROR'
 return 'UNVERIFIED','NO CURRENT STRATA CODE OBSERVATION'


def _overview(view):
 # The existing Operator snapshot is the only source for this one-page
 # projection. Missing probes remain UNVERIFIED; a connected API or model is
 # never silently promoted to executable/consented/healthy.
 dev=view.development if type(view.development) is dict else {}
 telemetry=view.telemetry
 def observed(key):
  value=dev.get(key)
  return str(value) if type(value) in (int,str) and value!='' else 'UNVERIFIED'
 def tile(label,value,detail,target):
  return (f'<a class="overview-tile" href="#{target}"><small>{_e(label)}</small>'
          f'<strong>{_e(value)}</strong><span>{_e(detail)}</span></a>')
 active=len(view.activity)
 actionable=observed('guard_actionable')
 waiting=observed('work_waiting_human')
 worker=observed('local9b_worker')
 queue=observed('local9b_queue_state')
 owner_raw=dev.get('approved_humanmodel_view')
 owner=(owner_raw if type(owner_raw) is str and owner_raw in
        {'UNVERIFIED','AVAILABLE','BLOCKED','STALE'} else 'UNVERIFIED')
 services=tuple(s for s in telemetry.services if type(s) is dict) if telemetry else ()
 known_services=tuple(s for s in services if type(s.get('ok')) is bool)
 service_ready=sum(s['ok'] is True for s in known_services)
 service_down=sum(s['ok'] is False for s in known_services)
 # The denominator includes unobserved services: 4 known successes and one
 # unknown must never be presented as 4/4 READY.
 service_value=(f'{service_ready} / {len(services)} READY' if services
                else 'UNVERIFIED')
 service_detail=(f'{service_down} DOWN · {len(services)-len(known_services)} UNVERIFIED'
                 ' · CURRENT PROBE SNAPSHOT')
 healthy=sum(1 for p in view.providers if p.health=='ONLINE')
 provider_count=len(view.providers)
 provider_health=f'{healthy} / {provider_count} ONLINE' if provider_count else 'UNVERIFIED'
 provider_detail=('CONNECTION HEALTH · NOT AN INFERENCE GRANT' if provider_count else
                  'NO CURRENT PROVIDER OBSERVATIONS · NOT AN INFERENCE GRANT')
 core='READY' if telemetry and telemetry.ready is True else 'NOT VERIFIED'
 checks='PASS' if telemetry and telemetry.ready is True else 'REVIEW SYSTEM DETAILS'
 index_age=dev.get('klm_lifecycle_snapshot_age_seconds')
 index_age=f'{index_age}s' if type(index_age) is int and 0 <= index_age <= 30 else 'UNKNOWN'
 # A fixed aggregate from the existing read-only owner DB. Never render
 # untrusted per-review reason strings or source/atom identities.
 triage=dev.get('klm_review_triage')
 triage_keys=('conflict','revision','qualifier','dependency','difference','duplicate','other')
 if (type(triage) is dict and set(triage)==set(triage_keys)
     and all(type(triage[k]) is int and 0<=triage[k]<=100000 for k in triage_keys)
     and type(dev.get('klm_unresolved_reviews')) is int
     and sum(triage.values())==dev['klm_unresolved_reviews']):
  triage_detail=('POTENTIAL CONFLICT '+str(triage['conflict'])+
                 ' · REVISION '+str(triage['revision'])+
                 ' · QUALIFIER '+str(triage['qualifier'])+
                 ' · DEPENDENCY '+str(triage['dependency'])+
                 ' · VALUE '+str(triage['difference'])+
                 ' · DUPLICATE '+str(triage['duplicate'])+
                 ' · OTHER '+str(triage['other']))
 else:
  triage_detail='UNVERIFIED'
 # Factory-flow diagram (SVG): a vertical pipeline the owner can read at a
 # glance. Each node shows a plain Japanese name and a short status; the full
 # technical strings stay available in the details block below the diagram.
 compute=tuple(getattr(view,'local_compute',()) or ())
 def _live(binding):
  return any(getattr(c,'binding',None)==binding and
             getattr(c,'active',None) is True for c in compute)
 routes=tuple(getattr(view,'routes',()) or ())
 klm_detail=((('CURRENT SYNC \u00b7 ' if observed('klm_status')=='CURRENT' else
   'RESCAN REQUIRED \u00b7 ' if observed('klm_status')=='RESCAN_REQUIRED' else
   'LAST DUE REPORT \u00b7 ' if observed('klm_status')=='NOT_DUE' else
   'LAST OWNER REPORT \u00b7 ')+
  'COVERAGE '+observed('klm_coverage')+
  ' \u00b7 CHANGES '+observed('klm_changes')+
  ' \u00b7 FOLDERS '+observed('klm_folders')+
  ' \u00b7 OBJECTS '+observed('klm_objects')+
  ' \u00b7 NOT SOURCE-REVISION PROOF') if observed('klm_status')!='UNVERIFIED'
  else 'NO CURRENT KLM FEED IN THIS OPERATOR VIEW')
 klm_processing=(('REVIEW REQUIRED' if any(dev.get(k,0) for k in
    ('klm_missing_features','klm_unresolved_reviews','klm_failed_intake'))
   else 'NO PENDING REVIEWS' if dev.get('klm_atoms') else 'NO INDEXED ATOMS')
  if dev.get('klm_lifecycle_state')=='OBSERVED' else 'UNVERIFIED')
 klm_processing_detail=('ATOMS '+observed('klm_atoms')+' \u00b7 MISSING FEATURES '+observed('klm_missing_features')+
  ' \u00b7 UNRESOLVED REVIEWS '+observed('klm_unresolved_reviews')+
  ' \u00b7 RELATIONS '+observed('klm_relations')+' \u00b7 FAILED INPUTS '+observed('klm_failed_intake')+
  ' \u00b7 REVIEW TRIAGE '+triage_detail+
  ' \u00b7 INDEX READ '+_observed(dev.get('klm_lifecycle_observed_at'))+
  ' \u00b7 SNAPSHOT AGE '+index_age+
  ' \u00b7 LOCAL INDEX SNAPSHOT \u00b7 SYNC STATUS IS SEPARATE')
 def _ja(value, table):
  return table.get(value, value)
 klm_ja=_ja(observed('klm_status'),{'CURRENT':'\u540c\u671f\u5b8c\u4e86','NOT_DUE':'\u5f85\u6a5f\u4e2d','RESCAN_REQUIRED':'\u518d\u78ba\u8a8d\u304c\u5fc5\u8981','POLL_FAILED':'\u8aad\u307f\u53d6\u308a\u5931\u6557','DRIVE_AUTH_REQUIRED':'\u518d\u8a8d\u8a3c\u304c\u5fc5\u8981','UNVERIFIED':'\u672a\u78ba\u8a8d'})
 processing_ja=_ja(klm_processing,{'REVIEW REQUIRED':'\u78ba\u8a8d\u5f85\u3061\u3042\u308a','NO PENDING REVIEWS':'\u78ba\u8a8d\u5f85\u3061\u306a\u3057','NO INDEXED ATOMS':'\u8cc7\u6599\u306a\u3057','UNVERIFIED':'\u672a\u78ba\u8a8d'})
 _rev=dev.get('klm_unresolved_reviews')
 if klm_processing=='REVIEW REQUIRED' and isinstance(_rev,int) and _rev>0: processing_ja='\u78ba\u8a8d\u5f85\u3061 '+str(_rev)+' \u4ef6'
 owner_ja=_ja(owner,{'UNVERIFIED':'\u672a\u78ba\u8a8d','AVAILABLE':'\u5229\u7528\u53ef','BLOCKED':'\u505c\u6b62\u4e2d','STALE':'\u53e4\u3044'})
 compute_ja={'STANDBY':'\u5f85\u6a5f\u4e2d','DISCOVERED':'\u63a5\u7d9a\u3042\u308a','UNAVAILABLE':'\u5fdc\u7b54\u306a\u3057','UNVERIFIED':'\u672a\u78ba\u8a8d','READY':'\u6b63\u5e38'}
 strata_value,strata_detail=_strata_overview(compute)
 strata_ja=_ja(strata_value,compute_ja)
 nineb_value,nineb_detail=_shared9b_overview(compute)
 nineb_ja=_ja(nineb_value,compute_ja)
 worker_value='SCHEDULED_CYCLE_BLOCKED' if queue=='SCHEDULED_CYCLE_BLOCKED' else worker
 worker_ja=_ja(worker_value,{'SCHEDULED_IDLE':'\u5f85\u6a5f\u4e2d','RUNNING':'\u5b9f\u884c\u4e2d','UNVERIFIED':'\u672a\u78ba\u8a8d','UNKNOWN':'\u672a\u78ba\u8a8d','RECONCILE_REQUIRED':'\u8981\u7167\u5408','SCHEDULED_CYCLE_BLOCKED':'\u505c\u6b62\u4e2d'})
 core_ja=_ja(core,{'READY':'\u6b63\u5e38','NOT VERIFIED':'\u672a\u78ba\u8a8d','UNVERIFIED':'\u672a\u78ba\u8a8d'})
 def _tone(value, good, warn):
  if value in warn: return '#e0bd45'
  if value in good: return '#56c7d9'
  if value in ('UNAVAILABLE','POLL_FAILED'): return '#c44348'
  return '#8da2ae'
 def _snode(x,y,w,name,sub,status,tone,target,live=False,waiting=False):
  cls='flow-svg-node'+(' live' if live else '')+(' waiting' if waiting else '')
  stroke='#c44348' if waiting else '#31566d'
  return (f'<a href="#{target}"><g class="{cls}">'
   f'<rect x="{x}" y="{y}" width="{w}" height="46" rx="8" fill="rgba(77,111,132,.11)" stroke="{stroke}"/>'
   f'<circle cx="{x+16}" cy="{y+23}" r="5" fill="{tone}"/>'
   f'<text x="{x+28}" y="{y+21}" font-size="14" font-weight="700" fill="#d9e4e9">{_e(name)}</text>'
   f'<text x="{x+28}" y="{y+37}" font-size="10" fill="#8da2ae">{_e(sub)}</text>'
   f'<text x="{x+w-10}" y="{y+21}" font-size="12" font-weight="700" fill="{tone}" text-anchor="end">{_e(status)}</text>'
   '</g></a>')
 def _varrow(y1,y2):
  return (f'<line x1="180" y1="{y1}" x2="180" y2="{y2-5}" stroke="#8da2ae" stroke-width="2"/>'
   f'<polygon points="175,{y2-6} 185,{y2-6} 180,{y2}" fill="#8da2ae"/>')
 def _caption(y,text):
  return f'<text x="10" y="{y}" font-size="12" letter-spacing="2" fill="#8da2ae">{_e(text)}</text>'
 def _lane(x,y,name,sub,status,tone,target,live=False):
  cls='flow-svg-node'+(' live' if live else '')
  return (f'<a href="#{target}"><g class="{cls}">'
   f'<rect x="{x}" y="{y}" width="96" height="52" rx="8" fill="rgba(77,111,132,.11)" stroke="#31566d"/>'
   f'<circle cx="{x+12}" cy="{y+14}" r="4" fill="{tone}"/>'
   f'<text x="{x+21}" y="{y+18}" font-size="12" font-weight="700" fill="#d9e4e9">{_e(name)}</text>'
   f'<text x="{x+8}" y="{y+34}" font-size="9" fill="#8da2ae">{_e(sub)}</text>'
   f'<text x="{x+8}" y="{y+47}" font-size="11" font-weight="700" fill="{tone}">{_e(status)}</text>'
   '</g></a>')
 active=str(active); actionable=str(actionable)
 worker_live=type(dev.get('direct_mcp_running')) is int and dev['direct_mcp_running']>0
 guard_waiting=actionable.isdigit() and int(actionable)>0
 has_active=active not in ('0','UNVERIFIED','')
 cloud_live=any(getattr(a,'kind',None)=='CLOUD' for a in getattr(view,'activity',()) or ())
 active_ja='\u51e6\u7406\u4e2d '+active+' \u4ef6' if has_active else '\u51e6\u7406\u4e2d\u306a\u3057'
 routes_ja=(str(len(routes))+' \u6a5f\u80fd') if routes else '\u672a\u78ba\u8a8d'
 approval_ja='\u627f\u8a8d\u5f85\u3061 '+actionable+' \u4ef6' if actionable not in ('0','UNVERIFIED') else '\u627f\u8a8d\u5f85\u3061\u306a\u3057'
 failed=observed('work_failed'); uncertain=observed('work_uncertain')
 _ap=[]
 if uncertain.isdigit() and int(uncertain)>0: _ap.append('\u4e0d\u78ba\u5b9f '+uncertain+' \u4ef6')
 if _ap: accept_ja=' \u00b7 '.join(_ap); accept_tone='#c44348'
 elif uncertain.isdigit(): accept_ja='\u554f\u984c\u306a\u3057'; accept_tone='#56c7d9'
 else: accept_ja='\u672a\u78ba\u8a8d'; accept_tone='#8da2ae'
 route_lines=[]
 _missing=[]
 for r in routes:
  if r.uses_llm_route and not (r.primary and r.primary!='\u2014'): _missing.append(str(r.function)+' \u2192 '+'\u672a\u5272\u5f53')
 if _missing: route_lines=_missing+['\u4ed6\u306f\u62c5\u5f53\u3042\u308a']
 elif routes: route_lines=['\u5168\u3066\u306e\u6a5f\u80fd\u306b\u62c5\u5f53\u3042\u308a']
 if not route_lines: route_lines=['\u672a\u78ba\u8a8d']
 def _fnode(y,lines):
  h=28+15*len(lines)
  rows=''.join(f'<text x="42" y="{y+27+i*15}" font-size="10" fill="#8da2ae">{_e(t)}</text>' for i,t in enumerate(lines))
  return (f'<g class="flow-svg-node"><rect x="30" y="{y}" width="300" height="{h}" rx="8" fill="rgba(77,111,132,.11)" stroke="#31566d"/>'
   f'<text x="42" y="{y+17}" font-size="11" font-weight="700" fill="#d9e4e9">\u6a5f\u80fd\u3054\u3068\u306e\u62c5\u5f53</text>{rows}</g>'), y+h
 parts=[]; y=0
 def _cap(text):
  nonlocal y; y+=16; parts.append(_caption(y,text)); y+=10
 def _node(name,sub,status,tone,target,live=False,waiting=False):
  nonlocal y; parts.append(_snode(30,y,300,name,sub,status,tone,target,live=live,waiting=waiting)); y+=46
 def _arr():
  nonlocal y; parts.append(_varrow(y,y+14)); y+=14
 _cap('\u5165\u529b\u3068\u77e5\u8b58')
 _node('\u30c9\u30e9\u30a4\u30d6\u306e\u68da\u5378\u3057','KLM DRIVE SYNC',klm_ja,_tone(observed('klm_status'),{'CURRENT','NOT_DUE'},{'RESCAN_REQUIRED'}),'system')
 _arr()
 _node('\u8cc7\u6599\u306e\u6574\u7406','KLM PROCESSING',processing_ja,_tone(klm_processing,{'NO PENDING REVIEWS','NO INDEXED ATOMS'},{'REVIEW REQUIRED'}),'development')
 _arr()
 _node('\u4eba\u9593\u30e2\u30c7\u30eb','HUMANMODEL',owner_ja,_tone(owner,{'AVAILABLE'},set()),'development')
 _cap('\u51e6\u7406')
 _node('\u4f9d\u983c\u306e\u53d7\u4ed8','TASK INTAKE',active_ja,'#56c7d9' if has_active else '#8da2ae','tasks',live=has_active)
 _arr()
 _node('\u632f\u308a\u5206\u3051','AUTOMATIC ROUTING',routes_ja,'#56c7d9' if routes else '#8da2ae','routing',live=has_active)
 _arr()
 fhtml,y=_fnode(y,route_lines); parts.append(fhtml)
 ly=y+14
 parts.append(f'<path d="M180 {y} V{ly-4} M60 {ly-4} H300 M60 {ly-4} V{ly} M180 {ly-4} V{ly} M300 {ly-4} V{ly}" stroke="#8da2ae" stroke-width="2" fill="none"/>')
 parts.append(_lane(12,ly,'\u5916\u90e8AI','LLM',provider_health,'#56c7d9' if provider_health.endswith('ONLINE') else '#8da2ae','settings',live=cloud_live))
 parts.append(_lane(132,ly,'\u30e1\u30a4\u30f3PC','MAINPC / STRATA',strata_ja,_tone(strata_value,{'DISCOVERED'},set()),'settings',live=_live('local:mainpc-strata:code-agent')))
 parts.append(_lane(252,ly,'M1 9B','SHARED 9B',nineb_ja,_tone(nineb_value,{'DISCOVERED'},set()),'settings',live=_live('local:ollama-shared9b:general')))
 y=ly+52
 parts.append(f'<path d="M60 {y} V{y+12} M180 {y} V{y+12} M300 {y} V{y+12} M60 {y+12} H300 M180 {y+12} V{y+18}" stroke="#8da2ae" stroke-width="2" fill="none"/>')
 y+=18
 _cap('\u958b\u767a\u3068\u53cd\u6620')
 _node('\u958b\u767a\u306e\u5b9f\u884c','DEVELOPMENT WORKER',worker_ja,_tone(worker_value,{'RUNNING','SCHEDULED_IDLE'},{'SCHEDULED_CYCLE_BLOCKED'}),'development',live=worker_live or worker=='RUNNING')
 _arr()
 _node('\u30c6\u30b9\u30c8\u3068\u53d7\u5165','ACCEPTANCE',accept_ja,accept_tone,'development')
 _arr()
 _node('\u627f\u8a8d','GUARD APPROVAL',approval_ja,'#e0bd45' if guard_waiting else '#8da2ae','development',waiting=guard_waiting)
 _arr()
 _node('\u672c\u756a\u53cd\u6620','PRODUCTION',core_ja,_tone(core,{'READY'},set()),'system')
 _arr()
 _node('\u6b63\u672c\uff08GitHub\uff09','GITHUB MAIN','MAIN','#56c7d9','system')
 svg=f'<svg class="flow-svg" viewBox="0 0 360 {y+8}" role="img" aria-label="FOUNDATION FLOW">'+''.join(parts)+'</svg>'
 return section('overview','OVERVIEW / FOUNDATION',svg)


def _primary_answer_html(n, *, echo=False):
 # Answers come from the existing owner-host primary-review event projection,
 # not from general notifications, model text or an independent approval.
 if (echo or n.kind != 'primary_review'
     or n.status != 'PRIMARY_REVIEW_RESOLVED' or n.level != 2):
  return ''
 answer, ref = n.automatic_answer, n.answer_reference
 fields = {'task_id','question_digest','evidence_sha256',
           'current_generation','related_work_status'}
 if (type(answer) is not str or not 0 < len(answer) <= 16000
     or type(ref) is not dict or set(ref) != fields):
  return ''
 if (type(ref['task_id']) is not str
     or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', ref['task_id']) is None
     or any(type(ref[k]) is not str
            or re.fullmatch(r'[a-f0-9]{64}',ref[k]) is None
            for k in ('question_digest','evidence_sha256'))
     or type(ref['current_generation']) is not bool
     or type(ref['related_work_status']) is not str
     or ref['related_work_status'] not in {
         'VERIFIED','UNVERIFIED','WAITING_HUMAN','FAILED','RUNNING',
         'RECOVERING','UNCERTAIN','PLANNED','CANCELLED'}):
  return ''
 current=ref['current_generation']
 label=('HumanModel 自動回答（暫定・本人未承認）' if current
        else 'HumanModel 過去の自動回答（現在の判断ではありません）')
 applicability=('現行の判断記録（適用・承認ではありません）' if current
                else '過去の判断記録・再適用不可')
 return (
  '<div class="humanmodel-auto-answer">'
  f'<b>{_e(label)}</b><small>{_e(applicability)}'
  f' · 作業状態 {_e(ref["related_work_status"])}</small>'
  f'<pre style="white-space:pre-wrap;overflow-wrap:anywhere">{_e(answer)}</pre>'
  f'<small>対象タスク <code>{_e(ref["task_id"])}</code>'
  f' · 判断世代 <code>{_e(ref["question_digest"])}</code>'
  f' · 根拠参照 <code>{_e(ref["evidence_sha256"])}</code></small>'
  '<small>異議・訂正はMuseなどから上記タスクと判断世代を指定して指示してください。'
  'この回答は本人の承認、Guardの許可、処理完了を意味しません。</small>'
  '</div>'
 )



def _development_recovery_panel(view):
 # The existing one-page Operator is the sole supervision surface. Use
 # canonical snapshot fields, not a new Work/Guard/review DB or a task runner.
 # No private request text or model output is inspected on this path.
 dev=getattr(view,'development',None) or {}
 if type(dev) is not dict: dev={}
 def count(key):
  val=dev.get(key)
  return str(val) if type(val) is int and 0<=val<=1000000 else 'UNVERIFIED'
 def state(key,allowed):
  val=dev.get(key)
  return val if type(val) is str and val in allowed else 'UNVERIFIED'
 pending=count('guard_actionable')
 unbound=count('guard_unbound')
 failed=count('work_failed')
 uncertain=count('work_uncertain')
 waiting=count('work_waiting_human')
 view_state=state('approved_humanmodel_view',{'UNVERIFIED','AVAILABLE','BLOCKED','STALE'})
 klm=state('klm_status',{
  'CURRENT','RESYNC_PARTIAL','REPLAY_PARTIAL','RESCAN_REQUIRED','NOT_DUE',
  'DRIVE_AUTH_REQUIRED','HOST_BINDING_BLOCKED','POLL_FAILED',
  'SYNC_ACTIVE_OR_RECONCILE_REQUIRED','CLOCK_RECONCILE_REQUIRED'})
 # An older/ambiguous model answer does not become permission or evidence of
 # approval; the actual Answer tile is rendered by the original notice path.
 answers=sum(bool(_primary_answer_html(n)) for n in view.notices)
 if failed!='UNVERIFIED' and int(failed)>0:
  failure_note=('過去の失敗Work '+failed+'件は残っています。通知の非表示では消えません。'
                '再実行せず、既存の原本・固定テスト・受入結果を確認してください。')
 else:
  failure_note=('失敗Workの状況は現在のGuard/Workから確認できません。'
                if failed=='UNVERIFIED' else '現在のWork集計に失敗状態はありません。')
 human_note=(
  'HumanModelの承認済みViewと回答忠実度は未検証です。'
  '既存の根拠付き自動回答は通知に表示され、Muse等から世代と根拠を指定して訂正できます。'
  if view_state!='AVAILABLE'
  else '承認済みViewの観測と、本人回答忠実度の受入は別の検査です。')
 answer_detail=(
  '<small>HUMANMODEL / PROVISIONAL NOTICE ANSWERS / '+str(answers)+
  ' · NOT OWNER CONSENT</small>')
 return panel(
  '<b>GUARD / CURRENT WORK · RECOVERY</b>'
  '<span>EXACT PENDING / '+_e(pending)+' · UNBOUND / '+_e(unbound)+'</span>'
  '<small>WORK FAILED / '+_e(failed)+' · UNCERTAIN / '+_e(uncertain)+
  ' · WAITING HUMAN / '+_e(waiting)+'</small>'
  '<small>LOCAL 9B WORKER / '+_e(state('local9b_worker',{
    'RUNNING','RECONCILE_REQUIRED','LAST_EXIT_NONZERO','SCHEDULED_IDLE','UNKNOWN'}))+
  ' · ELIGIBLE RECIPES / '+_e(count('eligible_recipes'))+'</small>'
  '<small>LOCAL 9B QUEUE / '+_e(state('local9b_queue_state',{
    'RUNNING','RECONCILE_REQUIRED','WORKER_EXIT_NONZERO','QUEUED_NOT_RUNNING',
    'NO_QUEUED_TASK','LOCAL_WORK_CYCLE_OBSERVED','SCHEDULED_CYCLE_BLOCKED',
    'UNAVAILABLE','UNKNOWN'}))+
  ' · QUEUED / '+_e(count('local9b_queued_count'))+
  ' · LAST FAILURE / '+_e(dev.get('local9b_last_failure_code') or 'UNVERIFIED')+'</small>'
  '<small>MCP LOCAL CODE / '+_e(state('direct_mcp_status',{
    'WORK_RECEIPTS_ONLY','NO_WORK_RECEIPTS'}))+
  ' · RUNNING / '+_e(count('direct_mcp_running'))+
  ' · LOCAL VERIFIED RECEIPTS / '+_e(count('direct_mcp_verified_receipts'))+
  ' · FAILED / '+_e(count('direct_mcp_failed'))+
  ' · LAST MODEL / '+_e(state('direct_mcp_last_route',{'UNVERIFIED','M1','STRATA'}))+'</small>'
  '<small>CODE REVIEW REQUIRED / '+_e(count('code_review_required'))+
  ' · ADMITTED REQUESTS / '+_e(count('code_admitted_requests'))+
  ' · FAILED LOCAL ATTEMPTS / '+_e(count('code_failed_local_attempts'))+
  ' · OWNER REVIEW IS NOT AUTOMATIC EXECUTION</small>'+
  '<small>APPROVED HUMANMODEL VIEW / '+_e(view_state)+
  ' · KLM OWNER SOURCE / '+_e(klm)+'</small>'
  +answer_detail+
  '<p>'+_e(failure_note)+'</p>'+
  '<p>'+_e(human_note)+'</p>'+
  '<small>CODEチケットの検証済み履歴と全体Workの失敗件数は別です。'
  '既存の本人レビュー・Guard・M1独立受入を省略しません。</small>',
  kind='telemetry',classes='telemetry'
 )

def render(view,surface='responsive',csrf='',reconcile_available=False,theme='I',human_input_available=False,chat_url='',mcp_owner_delegation=False):
 surface_policy=policy(surface)
 if theme not in {'C','I'}: raise ValueError('unknown theme')
 echo=surface_policy.name=='echo'
 active_routes={str(a.kind).upper() for a in view.activity}
 chat_link=f'<a class=external-link href="{_e(chat_url)}" aria-label="Open LibreChat">&#8599; CHAT</a>' if (chat_url and not echo) else ''
 nav=f'<nav><b>AI FOUNDATION</b><a href="#top">HOME</a><a href="#notifications">NOTIFICATIONS</a><a href="#overview">OVERVIEW</a><a href="#routing">ROUTING</a><a href="#settings">SETTINGS</a><a href="#development">DEVELOPMENT</a><a href="#tasks">TASKS</a><a href="#system">SYSTEM</a>{chat_link}</nav>' if not echo else '<nav><b>AI FOUNDATION</b><a href="#top">HOME</a><a href="#notifications">NOTIFICATIONS</a><a href="#system">SYSTEM</a></nav>'
 return_to={'responsive':'/','echo':'/echo'}[surface]
 switch='<div class=design-switch>'+action_form('/presentation/theme/toggle',csrf,'CHANGE DESIGN',role='secondary',fields=(('return_to',return_to),))+'</div>'
 ns=[]
 # Identical passive notices (no controls, no automatic answer) are shown
 # once with a count instead of flooding the page with duplicate cards.
 def _passive(n):
  # Intrinsic to the notice: an approval or input request is never passive,
  # on any surface, even one that does not render its controls.
  return not (n.actionable or n.input_required or n.status=='UNCERTAIN')
 _notice_counts={}
 _notice_groups={}
 for n in view.notices:
  if _passive(n):
   k=(n.level,n.status,n.summary_ja,n.detail_ja)
   _notice_counts[k]=_notice_counts.get(k,0)+1
   _notice_groups.setdefault(k,[]).append(n)
 _notice_seen=set()
 for n in view.notices:
  controls=''
  return_to='/echo' if echo else '/'
  if surface_policy.approvals and n.actionable:
   # Only the original Operator Guard owner actions appear in this UI.
   # MCP delegated grants, replay, verify-outcome and dismiss stay out of
   # the approval surface. The exact durable Guard route is unchanged.
   approval_fields=(('return_to',return_to),('approval_ref',n.approval_ref))
   controls=action_form(f'/action/approve/{n.subject}',csrf,'AUTHORIZE',role='confirm',fields=approval_fields)+action_form(f'/action/cancel/{n.subject}',csrf,'DENY',role='danger',fields=approval_fields)
  elif surface_policy.human_input and n.input_required:
   # Additional instruction uses only the original host-bound input path.
   controls=(f'<form method="post" action="/action/respond/{_e(n.subject)}"><input type=hidden name=csrf value="{_e(csrf)}"><input type=hidden name=return_to value="{_e(return_to)}"><input class="ui-field field-text" name=response maxlength=4000 placeholder="追加命令・必要な情報" required><button class="ui-button role-confirm">追加命令</button></form>' if human_input_available else '<small>追加命令：入力経路未接続</small>')
  elif n.status=='UNCERTAIN':
   # An uncertain effect cannot be presented as a fresh approval or retry.
   controls='<small>結果未確定・既存の独立読戻しで照合が必要です</small>'
  elif _passive(n) and not echo:
   # Passive notices can be hidden by the owner. The underlying work state
   # is unchanged; dismissal only removes the card from this surface.
   controls=action_form(f'/notification/dismiss/{n.subject}',csrf,'DISMISS',role='secondary',fields=(('return_to',return_to),))
  severity={1:'INFO',2:'NOTICE',3:'ATTENTION',4:'ACTION',5:'CRITICAL'}[n.level]
  auto_html=_primary_answer_html(n,echo=echo)
  decisions=f'<div class=decision>{controls}</div>' if controls else ''
  if _passive(n) and not auto_html and _notice_counts.get((n.level,n.status,n.summary_ja,n.detail_ja),0)>1:
   k=(n.level,n.status,n.summary_ja,n.detail_ja)
   if k in _notice_seen: continue
   _notice_seen.add(k)
   group_rows=''
   if not echo:
    subjects='\n'.join(m.subject for m in _notice_groups[k])
    group_rows=action_form('/notification/dismiss/group',csrf,'DISMISS ALL',role='secondary',fields=(('return_to',return_to),('subjects',subjects)))
   ns.append(panel(f'<b>LV{n.level} {severity} / {_e(n.status)} \u00d7{_notice_counts[k]}</b><span>{_e(n.summary_ja)}</span>{auto_html}<small>{_e(n.detail_ja)}</small>{group_rows}',kind='notice',classes=f'notice lv{n.level}'))
   continue
  ns.append(panel(f'<b>LV{n.level} {severity} / {_e(n.status)}</b><span>{_e(n.summary_ja)}</span>{auto_html}<small>{_e(n.detail_ja)}</small><small>{_e(n.subject)}</small>{decisions}',kind='notice',classes=f'notice lv{n.level}'))
 notices=''.join(ns) or panel('現在、対応が必要な通知はありません。',kind='quiet',classes='quiet')
 tasks='' if not surface_policy.tasks else (''.join(panel(f'<b>{_e(t.status)}</b><span>{_e(t.text)}</span><small>{_e(t.result)}</small><small>{_e(t.verification)} · METHOD {_e(t.route_kind)}{f' / {_e(t.route_binding)}' if t.route_binding else ''} · DETAILS {_e(", ".join(t.evidence) if t.evidence else "—")}</small>',kind='task',classes='row') for t in view.tasks) or panel('NO ACTIVE TASKS',kind='quiet',classes='quiet'))
 providers=''.join(_provider_panel(p,view) for p in sorted(view.providers,key=lambda p:(p.short_remaining is None, p.short_remaining if p.short_remaining is not None else float('inf'), p.provider))) or panel('NO CLOUD LLM',kind='quiet',classes='quiet')
 credentials='' if echo else ''.join(f'<article class="ui-panel panel-credential credential"><b>{_e(c["provider"])}</b><span>{_e(c["tier"])} · {_e(c["health"])}</span><small>LAST CHECK · {_e(_observed(c.get("updated_at")))} · STATUS NOTE · {_e(c.get("reason"))}</small><div class=decision><form method=post action="/settings/provider/refresh/{_e(c["action_token"])}"><input type=hidden name=csrf value="{_e(csrf)}"><input type=hidden name=return_to value="/"><button class="ui-button role-secondary">CHECK</button></form><form method=post action="/settings/provider/replace/{_e(c["action_token"])}"><input type=hidden name=csrf value="{_e(csrf)}"><input type=hidden name=return_to value="/"><input class="ui-field field-password" type=password name=api_key autocomplete=off placeholder="NEW KEY" required><button class="ui-button role-confirm">CHANGE KEY</button></form><form method=post action="/settings/provider/remove/{_e(c["action_token"])}"><input type=hidden name=csrf value="{_e(csrf)}"><input type=hidden name=return_to value="/"><button class="ui-button role-danger">REMOVE</button></form></div></article>' for c in view.credentials)
 local=_local_panel(view.local_compute,view,active_routes)
 development_panel=_development_recovery_panel(view)
 routes=''.join(_route_panel(r,view) for r in view.routes) or panel('NO LLM ROUTE',kind='quiet',classes='quiet')
 telemetry=''
 if view.telemetry:
  t=view.telemetry
  bad=sum(1 for x in t.checks if x.get('ok') is False)
  down=sum(1 for x in t.services if x.get('ok') is False)
  unchecked=sum(1 for x in t.checks if type(x.get('ok')) is not bool)
  unobserved=sum(1 for x in t.services if type(x.get('ok')) is not bool)
  backup='NONE' if not t.backup else ('PRESENT' if t.backup.get('present') else 'ABSENT')
  update='NONE' if not t.update else (t.update.get('transaction') or ('STAGED' if t.update.get('staged') else 'IDLE'))

  check_detail=' · '.join(
   f'{_e(x.get("name"))} {"OK" if x.get("ok") is True else "FAILED" if x.get("ok") is False else "UNVERIFIED"}'
   for x in t.checks
  )
  service_detail=' · '.join(
   f'{_e(x.get("name"))} {"OK" if x.get("ok") is True else "DOWN" if x.get("ok") is False else "UNVERIFIED"}'
   for x in t.services
  )

  details=[]
  if bad:
   details.append(f'CHECKS FAILED / {bad}')
  if down:
   details.append(f'SERVICES DOWN / {down}')
  if unchecked:
   details.append(f'CHECKS UNVERIFIED / {unchecked}')
  if unobserved:
   details.append(f'SERVICES UNVERIFIED / {unobserved}')
  if backup not in ('NONE','—',''):
   details.append(f'BACKUP / {backup}')
  if update not in ('NONE','—','IDLE',''):
   details.append(f'UPDATE / {update}')
  if check_detail:
   details.append(check_detail)
  if service_detail:
   details.append(service_detail)

  if t.ready is True:
   extras=[]
   if update not in ('NONE','—','IDLE',''): extras.append(f'UPDATE / {_e(update)}')
   if service_detail: extras.append(f'<details><summary>DETAILS</summary>{service_detail}</details>')
   telemetry=panel('<b>SYSTEM READY</b><span>ALL CORE CHECKS PASSED</span>'+''.join(extras),kind='telemetry',classes='telemetry')
  else:
   status='SYSTEM ATTENTION'
   telemetry=panel(
    f'<b>{status}</b><span>{" · ".join(details)}</span>',
    kind='telemetry',
    classes='telemetry'
   )
 labels=('LV5 CRITICAL','LV4 ACTION','LV3 ATTENTION','LV2 NOTICE','LV1 INFO')
 hero=f'<section class="hero"><small>SYSTEM STATUS</small><h1>{_e(view.runtime_health)}</h1><small>作業の状態 · {_e(view.state)}</small><div class=metrics>{"".join(metric(view.severity_counts[level-1],label) for level,label in zip((5,4,3,2,1),labels))}</div></section>'
 notice_section=section('notifications','NOTIFICATIONS',notices)
 if echo:
  body=hero+notice_section+section('system','SYSTEM',telemetry)
 else:
  body=hero+notice_section+_overview(view)
  settings_chunk=f'''<details id="settings" class="fold"><summary>LLM SETUP</summary><div class=cards>{providers}{local}<form class="ui-panel panel-capacity provider" method=post action=/settings/provider/add><input type=hidden name=csrf value="{_e(csrf)}"><input type=hidden name=return_to value="/"><b>ADD API</b><input class="ui-field field-password" type="password" name=api_key autocomplete=off placeholder="API KEY" required><label class="provider-type-label">API TYPE<select id="provider-select" class="ui-field field-select" name=provider><option value="">AUTO DETECT</option>{"".join(f"<option>{_e(name)}</option>" for name in PROVIDER_NAMES)}</select></label><details id="provider-options"><summary>MORE OPTIONS</summary><small id="provider-warning" class="hint" hidden>\u30ad\u30fc\u306e\u7a2e\u985e\u3092\u5224\u5225\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002API TYPE\u3092\u9078\u3093\u3067\u304f\u3060\u3055\u3044\u3002</small><select class="ui-field field-select" name=tier title="FREE\u306f\u7121\u6599 / PAID\u306f\u8ab2\u91d1\u3042\u308a"><option>FREE</option><option>PAID</option></select></details><button class="ui-button role-confirm">CONNECT</button><small>FREEは無料・PAIDは課金あり</small></form></div><details><summary>API CONNECTIONS</summary>{credentials or panel('NO API CONNECTED',kind='quiet',classes='quiet')}</details></details>'''
  routing_chunk=f'''<details id="routing" class="fold"><summary>AUTOMATIC ROUTING</summary><div class=routes>{routes}</div><details><summary>COST CONTROL</summary>
<div class="route-cost-status">
<b>PAID API · DISABLED</b>
<small>有料の経路は使わない設定です。</small>
</div>
</details><form method=post action=/settings/routing/optimize><input type=hidden name=csrf value="{_e(csrf)}"><input type=hidden name=return_to value="/"><input type=hidden name=function value=ALL><button class="ui-button role-secondary">UPDATE ROUTES</button></form></details>'''
  body+=routing_chunk+settings_chunk
  body+=section('development','DEVELOPMENT / APPROVAL',development_panel,fold=True)
  body+=section('tasks','TASKS',tasks,fold=True)
  body+=section('system','SYSTEM',telemetry,fold=True)
 if not echo: body+='<div class=scroll-tail aria-hidden=true></div>'
 css=styles(surface,theme)
 refresh=''
 sync_script="<script>(()=>{const q=new URLSearchParams(location.search),providerError=q.get('provider_error')||location.hash.includes('provider_error=selection_required')?'selection_required':'';if(providerError==='selection_required'){const d=document.getElementById('provider-options'),w=document.getElementById('provider-warning'),s=document.getElementById('provider-select');if(d)d.open=true;if(w)w.hidden=false;if(s){s.focus();s.style.outline='3px solid currentColor';s.scrollIntoView({block:'center'})}}})()</script>"
 return f'<!doctype html><html lang=ja><head>{refresh}<meta name="ai-foundation-theme" content="{theme}"><meta name=viewport content="width=device-width,initial-scale=1"><style>{css}</style></head><body><main id=top class={surface}>{nav}<div class=content>{switch}{body}</div></main>{sync_script}</body></html>'



