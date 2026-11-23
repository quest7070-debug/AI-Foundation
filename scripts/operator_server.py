#!/usr/bin/env python3
import argparse,threading,os,time,sys
from pathlib import Path

# The original Guard-installed launchd command runs this absolute script.
# Python then searches its scripts/ directory and the exactly pinned
# src/:experiments/ directories, NOT the repository root (even though the
# launchd WorkingDirectory is the same root). CODE owner review needs
# scripts.m1_operator_release_cli to authenticate the physically installed
# immutable source; without this bootstrap it silently fails closed and the
# Operator review HTML shows zero ticket preview actions.
#
# Bind package imports to THIS running entrypoint's canonical source root,
# not to AI_FOUNDATION_REPO_ROOT (CODE workspaces), the shell CWD, an untrusted
# environment variable, a candidate PR, or any newly granted Guard scope.
# Earlier installed release plist/env contracts stay byte-for-byte unchanged
# so an existing VERIFIED incumbent can still be attested during replacement.
_OPERATOR_SCRIPT = Path(__file__).resolve(strict=True)
_OPERATOR_SOURCE_ROOT = _OPERATOR_SCRIPT.parents[1]
if (not (_OPERATOR_SOURCE_ROOT / "scripts" / "operator_server.py").is_file()
        or (_OPERATOR_SOURCE_ROOT / "scripts" / "operator_server.py"
            ).resolve(strict=True) != _OPERATOR_SCRIPT
        or not (_OPERATOR_SOURCE_ROOT / "src" / "ai_foundation").is_dir()):
    raise RuntimeError("OPERATOR_IMPORT_SOURCE_UNVERIFIED")
if str(_OPERATOR_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_OPERATOR_SOURCE_ROOT))
from ai_foundation.productization import load_config
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.guard import GuardCore
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.operator_server import OperatorApplication,serve
from ai_foundation.settings_service import SettingsService
from ai_foundation.provider_probe import LiveProviderProbe
from ai_foundation.http_transport import UrllibCloudTransport
from ai_foundation.local_compute_registry import LocalComputeRegistry
from ai_foundation.llama_swap_adapter import LlamaSwapDiscovery
from ai_foundation.llama_swap_adapter import LlamaSwapExecution
from ai_foundation.compute_routing import ComputeRouter
from ai_foundation.inference_service import GuardedInferenceService
from ai_foundation.durable_inference import SQLiteInferenceAttemptStore
from ai_foundation.core import TaskPlan,CanonContract
from ai_foundation.human_input import HumanInputService
from ai_foundation.cloud_execution import ObservedCloudExecution
from ai_foundation.provider_observer import ProviderResponseObserver
from ai_foundation.execution_activity import ExecutionActivityRegistry
from ai_foundation.reconciliation_registry import SQLiteReconciliationRegistry,ReconciliationService
from ai_foundation.native_credentials import MacOSNativeCredentialStore
from ai_foundation.push_credentials import VapidCredentialStore
from ai_foundation.webpush_transport import WebPushConfig,WebPushTransport
from ai_foundation.push_dispatch import PushDispatch

def main():
 p=argparse.ArgumentParser(); p.add_argument('--config',required=True); p.add_argument('--port',type=int,default=8766); a=p.parse_args()
 c=load_config(a.config); root=Path(c.data_dir); root.mkdir(parents=True,exist_ok=True)
 from ai_foundation.authority_manifest import verify as verify_authority_manifest,establish as establish_authority_manifest
 verify_authority_manifest(root,c)
 from ai_foundation.storage_admission import StorageAdmission,DEFAULT_MIN_FREE_BYTES
 storage_admission=StorageAdmission(root,min_free_bytes=int(os.getenv('AI_FOUNDATION_MIN_WRITE_FREE_BYTES',str(DEFAULT_MIN_FREE_BYTES))))
 guard_store=SQLiteGuardStore(root/c.guard_db,storage_admission=storage_admission); guard=GuardCore(guard_store.runtime_state(),store=guard_store)
 from ai_foundation.mcp_owner_grants import McpOwnerGrants
 mcp_owner_delegations=McpOwnerGrants(guard_store,initialize=True)
 activity=ExecutionActivityRegistry()
 from ai_foundation.observability import JsonlTraceSink,Tracer
 tracer=Tracer(JsonlTraceSink(root/c.trace_file))
 from ai_foundation.inference_composition import build_inference_composition
 inference_composition=build_inference_composition(root=root,config=c,guard=guard,activity=activity,storage_admission=storage_admission,tracer=tracer)
 infer=inference_composition.service;settings=inference_composition.settings;local_compute=inference_composition.local_compute;transport=inference_composition.transport
 from ai_foundation.provider_recovery import ProviderRecoveryLoop
 provider_recovery=ProviderRecoveryLoop(settings,interval=int(os.getenv('AI_FOUNDATION_PROVIDER_RECOVERY_SECONDS','60')))
 provider_recovery.start()
 from ai_foundation.retention import RetentionService,RetentionLoop
 retention=RetentionLoop(RetentionService(root/c.guard_db,root/c.work_db,root/c.inference_db),interval=int(os.getenv('AI_FOUNDATION_RETENTION_SECONDS','86400')))
 retention.start()
 from ai_foundation.long_term_health import LongTermHealthLoop,LongTermHealthEvidenceStore,check_long_term_health
 # Reuse the existing host maintenance cadence. The worker cannot replace
 # itself. Run the exact installed source from the separate Operator process;
 # ordinary status reads and web push remain observation-only.
 maintenance_status=None
 def reconcile_local_worker():
  nonlocal maintenance_status
  if os.getuid()!=501 or sys.platform!='darwin':return
  try:
   import subprocess,json
   from scripts.m1_development_ticket_factory import _owner_local_repo
   from scripts.m1_development_review_candidate import _installed_live_source_repo
   stage=_installed_live_source_repo(_owner_local_repo())
   env={key:os.environ[key] for key in ('HOME','USER','PATH','TMPDIR','LANG','LC_ALL') if key in os.environ}
   env['PYTHONPATH']=str(stage/'src')+':'+str(stage)
   env['PYTHONDONTWRITEBYTECODE']='1'
   result=subprocess.run([sys.executable,'-B','-m','scripts.m1_github_owner_local9b_release','--local-reconcile'],cwd=stage,env=env,capture_output=True,text=True,check=False)
   state=json.loads(result.stdout).get('status')
   if state not in {'WAITING_HUMAN','VERIFIED','WORKER_REGISTERED','DENIED','BLOCKED'}:state='UNVERIFIED'
  except Exception:state='UNVERIFIED'
  if state!=maintenance_status:
   print('LOCAL_WORKER_RELEASE '+state,flush=True);maintenance_status=state
 long_term_health=LongTermHealthLoop(lambda:check_long_term_health(root,storage_admission=storage_admission),interval=int(os.getenv('AI_FOUNDATION_LONG_TERM_HEALTH_SECONDS','3600')),evidence_store=LongTermHealthEvidenceStore(root/'long-term-health.json'),maintenance=reconcile_local_worker)
 def run_task(receipt):
  plan=TaskPlan(receipt.job_id,'compute','llm',text=receipt.text,canon_revision='human-ui',effect_id=receipt.job_id+':inference',privacy_text=getattr(receipt,'privacy_text',None))
  return infer.run(plan,CanonContract('human-ui','human-ui'),getattr(receipt,'function','CHAT'))
 def resume_waiting(job_id,position):
  # Current production intake has one step. The durable response is consumed only
  # when that exact waiting step is resumed; unrelated work is never touched.
  if position != 0: raise ValueError('unsupported intake position')
  response=app.intake.store.pending_human_input(job_id,position)
  if response is None: raise ValueError('human input missing')
  if not app.intake.store.human_input_context_valid(job_id,position): raise ValueError('human input context changed')
  # The response is durable context for the resumed work, never authority.
  def run_with_response(receipt):
   enriched=type(receipt)(receipt.job_id, receipt.text+'\n\nHuman response: '+response, receipt.created_at)
   return run_task(enriched)
  result=app.intake.execute(job_id,run_with_response)
  if app.intake.store.load(job_id)[position].status.value=='VERIFIED': app.intake.store.consume_human_input(job_id,position)
  return result
 actions=OperatorActions(guard)
 reconciliation_registry=SQLiteReconciliationRegistry(root/c.reconciliation_db,storage_admission=storage_admission)
 verification_ports={}
 # SEARCH and other non-MCP capability execution must survive independently of
 # optional ToolHive runtime state. ToolHive enriches this same host boundary
 # only when its runtime is actually available; its absence never widens grants.
 from ai_foundation.capability_execution import CapabilityExecutor
 from ai_foundation.toolhive_owner_runtime import owner_toolhive_binary
 from ai_foundation.protected_resources import production_protected_resources
 capability_executor=CapabilityExecutor(infer,guard,reconciliation_registry=reconciliation_registry,protected=production_protected_resources(root),activity=activity,tracer=tracer)
 composition=None; tool_port=None; repo_port=None; repo_root=None
 thv=owner_toolhive_binary(); tool_root=Path(os.getenv('AI_FOUNDATION_TOOLHIVE_ROOT','/tmp/ai-foundation-toolhive'))
 if thv is not None:
  from ai_foundation.toolhive import TOOLHIVE_FILESYSTEM_BINDING
  from ai_foundation.capability_composition import build_capability_composition
  composition=build_capability_composition(repo_base=Path(__file__).parents[1],data_root=root,config=c,inference=infer,guard=guard,reconciliation_registry=reconciliation_registry,activity=activity,thv_path=thv)
  composition.executor.tracer=tracer
  tool_port=composition.file_port;repo_port=composition.repo_port;repo_root=composition.repo_root;tool_root=composition.tool_root;capability_executor=composition.executor
  verification_ports[TOOLHIVE_FILESYSTEM_BINDING]=tool_port
 attachment_handoff=None
 try:
  from ai_foundation.librechat_mongo_lookup import LibreChatMongoQuery
  from ai_foundation.librechat_attachment_lookup import LibreChatAttachmentLookup
  from ai_foundation.attachment_handoff import AttachmentHandoff,AttachmentCleanupLoop
  uploads_root=Path(os.getenv('AI_FOUNDATION_LIBRECHAT_UPLOADS',str(Path.home()/'Library/Application Support/AI-Foundation/librechat/uploads')))
  images_root=Path(os.getenv('AI_FOUNDATION_LIBRECHAT_IMAGES',str(Path.home()/'Library/Application Support/AI-Foundation/librechat/images')))
  if uploads_root.exists():
   attachment_handoff=AttachmentHandoff(uploads_root,LibreChatAttachmentLookup(uploads_root,LibreChatMongoQuery(),images_root=images_root if images_root.exists() else None),storage_admission=storage_admission, trusted_roots=tuple(x for x in (uploads_root, images_root if images_root.exists() else None) if x is not None))
   attachment_handoff.recover_stale_leases()
   attachment_cleanup=AttachmentCleanupLoop(attachment_handoff,max_age_seconds=int(os.getenv('AI_FOUNDATION_HANDOFF_MAX_AGE_SECONDS','86400')),interval=int(os.getenv('AI_FOUNDATION_HANDOFF_CLEANUP_SECONDS','3600')))
   attachment_cleanup.start()
   capability_executor.attachment_handoff=attachment_handoff
 except Exception:
  attachment_handoff=None

 # VISION is an inference capability, not a ToolHive capability. Keep model
 # selection in the canonical ComputeRouter and preserve the runtime execution
 # slot separately from model identity.
 from ai_foundation.vision_routing import RoutedVisionBackend
 from ai_foundation.vision_execution import VisionExecutionPort
 from ai_foundation.openai_vision_adapter import OpenAICompatibleVision

 def local_vision_factory(route):
  selected=route.execution_slot or route.model
  if not selected:
   raise RuntimeError('local VISION route missing execution model')
  return OpenAICompatibleVision('http://127.0.0.1:9292',selected)

 def cloud_vision_factory(route):
  # No cloud provider currently owns VISION authority. Do not infer it from
  # generic CHAT capability or credentials.
  raise RuntimeError('cloud VISION backend unavailable')

 vision_backend=RoutedVisionBackend(
  infer.router,
  local_vision_factory,
  cloud_vision_factory,
 )
 capability_executor.vision_port=VisionExecutionPort(
  vision_backend,
  attachment_handoff,
 )

 from ai_foundation.capability_factory import build_daily_capability
 # Only signed scope keys may select host-owned roots. Optional ToolHive-backed
 # roots simply do not exist when ToolHive is unavailable; SEARCH/CHAT remains valid.
 files_scope=os.getenv('AI_FOUNDATION_FILES_SCOPE_KEY','files-default')
 repo_scope=os.getenv('AI_FOUNDATION_REPO_SCOPE_KEY','repo-default')
 data_json_scope=os.getenv('AI_FOUNDATION_DATA_JSON_SCOPE_KEY','json-summary')
 file_roots={files_scope:str(tool_root)} if tool_port is not None else {}
 repo_roots={repo_scope:str(repo_root)} if repo_port is not None else {}
 data_operations={data_json_scope:'json_summary'}
 def capability_factory(headers,payload,a):
  resolved=a
  if a is not None and a.attachment_ids:
   if attachment_handoff is None: raise ValueError('attachment handoff unavailable')
   grants=attachment_handoff.resolve(a.owner_id,a.attachment_ids)
   resolved=type('AttachmentContext',(),{'attachment_ids':tuple(x.attachment_id for x in grants),'attachments':grants,'owner':a.owner_id,'owner_id':a.owner_id})()
  return build_daily_capability(
  headers,payload,resolved,
  repo_roots=repo_roots,
  file_roots=file_roots,
  data_operations=data_operations,
  ambient_scopes={
   'repo':repo_scope,
   'files':files_scope,
   'data':data_json_scope,
  },
 )
 def long_term_notices():
  from ai_foundation.human_operations import HumanNotice
  from ai_foundation.external_log_maintenance import ExternalLogMaintenanceStateStore,external_log_maintenance_notice
  operational=[]
  health=long_term_health.trustworthy(stale_after=int(os.getenv('AI_FOUNDATION_LONG_TERM_HEALTH_STALE_SECONDS',str(long_term_health.interval*2))))
  if health is None:
   operational.append(HumanNotice(3,'system','long-term-health','FAILED','Long-term health evidence is stale.','Automatic long-term verification has not produced fresh evidence. Check the Operator health loop.',False,False,time.time()))
  else:
   failed=tuple(x for x in health.signals if not x.ok)
   if failed:
    detail='; '.join(f'{x.name}: {x.detail}' for x in failed[:4])
    operational.append(HumanNotice(3,'system','long-term-health','FAILED','Long-term health requires attention.',detail,False,False,health.checked_at))
  operational.extend(external_log_maintenance_notice(ExternalLogMaintenanceStateStore(root/'external-log-maintenance.json')))
  # Share one durable primary-review event projection with UI, /api/human and
  # the existing Web Push observer; never create notices for routine ticks.
  from ai_foundation.primary_review_events import primary_review_notices
  operational.extend(primary_review_notices(root/c.work_db))
  return tuple(operational)
 # Reuse the existing no-model M1 read-only worker status path. Cache one
 # bounded observation rather than running launchctl/file inspection on each
 # UI poll. This never starts or locks the 9B model or touches the job queue.
 from ai_foundation.operator_server import cached_owner_development_status
 @cached_owner_development_status
 def installed_development_status():
  try:
   from m1_runtime_status_probe import AUTODEV, _domain_status, autodev_status
   uid=os.getuid()
   domains=("gui/"+str(uid),"user/"+str(uid),"system")
   owner_domains={domain:_domain_status(AUTODEV,domain) for domain in domains}
   current=autodev_status(Path.home(),time.time(),owner_domains)
   # Reuse the same cached 30-second owner probe. Read only the fixed
   # KLM LaunchAgent's existing private report; no Drive, model or DB scan.
   try:
    from m1_klm_status_probe import (
        _fixed_service_paths, _json_owner, _freshness,
        MAX_REPORT, REPORT_STATUSES, COVERAGE_STATUSES, CHANGES_STATUSES,
        _status, _count)
    report_path,_=_fixed_service_paths(Path.home())
    report,info=_json_owner(report_path,MAX_REPORT)
    freshness=_freshness(info,time.time())
    status=report.get("status")
    fresh=freshness.get("report_fresh") is True
    current["klm"]={
        "status": status if type(status) is str and status in REPORT_STATUSES
                      else "UNVERIFIED",
        "fresh": fresh,
    }
    if fresh:
     # Existing report-only evidence, not another Drive call or scan.
     current["klm"].update({
         "coverage": _status(report.get("coverage"),COVERAGE_STATUSES),
         "changes": _status(report.get("changes"),CHANGES_STATUSES),
         "folders": _count(report.get("folders")),
         "objects": _count(report.get("objects")),
         "pages": _count(report.get("pages")),
     })
   except Exception:
    current["klm"]={"status":"UNVERIFIED","fresh":False}
  except Exception:
   current={"state":"UNAVAILABLE","queue_state":"UNAVAILABLE"}
  # HumanModel: read the fixed bindings file and the bound ledger view's
  # stale flag (read-only, bounded). Fail closed: no observation keeps the
  # dashboard at UNVERIFIED instead of inventing an approved view.
  try:
   import json as _hm_json, sqlite3 as _hm_sqlite
   from contextlib import closing as _hm_closing
   _hm_bindings_path=root/'human-model-bindings.json'
   if _hm_bindings_path.is_file() and not _hm_bindings_path.is_symlink() and _hm_bindings_path.stat().st_size<=65536:
    _hm_binding=_hm_json.loads(_hm_bindings_path.read_text())['bindings'][0]
    _hm_ledger=Path(_hm_binding['root'])/'ledger'/'human_model.sqlite3'
    if _hm_ledger.is_file():
     with _hm_closing(_hm_sqlite.connect(_hm_ledger.as_uri()+'?mode=ro',uri=True,timeout=2)) as _hm_db:
      _hm_row=_hm_db.execute('SELECT stale FROM model_views WHERE id=?',(_hm_binding['view_id'],)).fetchone()
     current['humanmodel']={'view':'BLOCKED' if _hm_row is None else 'STALE' if _hm_row[0] else 'AVAILABLE'}
  except Exception:
   pass
  # Read the SAME canonical Work DB at the existing 30-second M1 probe rate.
  # These are local CODE receipts, not authenticated caller connections,
  # main integration or currently installed source revision proof.
  try:
   import sqlite3,json
   from contextlib import closing
   db_path=root/c.work_db
   if not db_path.is_file() or db_path.is_symlink():
    raise ValueError("DIRECT_WORK_DB_NOT_VERIFIED")
   with closing(sqlite3.connect(db_path.resolve().as_uri()+"?mode=ro",
                                uri=True,timeout=2)) as db:
    rows=db.execute(
      "SELECT status,result,updated_at FROM work_steps "
      "WHERE job_id GLOB 'mcp-local-development:*' AND position=0 "
      "ORDER BY updated_at DESC LIMIT 32").fetchall()
    review_rows=db.execute(
       "SELECT status,COUNT(*) FROM work_steps "
       "WHERE job_id GLOB 'mcp-development-request:*' "
       "AND position=0 AND name='development-request' "
       "GROUP BY status ORDER BY status LIMIT 8").fetchall()
   direct={"state":"WORK_RECEIPTS_ONLY" if rows else "NO_WORK_RECEIPTS",
           "running":sum(x[0]=="RUNNING" for x in rows),
           "verified_receipts":0,
           "failed":sum(x[0]=="FAILED" for x in rows),
           "updated_at":max((x[2] for x in rows if type(x[2]) in (float,int)),default=None),
           "last_route":"UNVERIFIED"}
   for status,raw,_ in rows:
    if status != "VERIFIED":continue
    try:
     receipt=json.loads(raw)
     from re import fullmatch
     if (type(receipt) is dict
         and receipt.get("status")=="TESTED_CHANGE"
         and type(receipt.get("sha256")) is str
         and fullmatch(r"[a-f0-9]{64}",receipt["sha256"])):
      direct["verified_receipts"]+=1
      if direct["last_route"]=="UNVERIFIED":
       route=receipt.get("execution_binding")
       if route=="local:mainpc-strata:code-agent":direct["last_route"]="STRATA"
       elif route in {"local:llama-swap:local-code-agent","local:ollama-shared9b:general"}:direct["last_route"]="M1"
    except (ValueError,TypeError,AttributeError):pass
   current["direct_mcp"]=direct
   # The existing Work store is the sole source; status totals are read
   # inside the same bounded owner observation, never one source scan per UI
   # request. Failed-local counts are historical, not runnable retries.
   if (all(type(state) is str and state in
           {"WAITING_HUMAN","VERIFIED","FAILED","CANCELLED"}
           and type(total) is int and 0<=total<=100000
           for state,total in review_rows)
       and len(review_rows)<=4):
    review=dict(review_rows)
    current["development_backlog"]={
      "source":"CURRENT_OWNER_WORK",
      "review_required":review.get("WAITING_HUMAN",0),
      "admitted":review.get("VERIFIED",0),
      "failed_local_attempts":direct["failed"],
    }
  except Exception:
   current["direct_mcp"]={"state":"UNVERIFIED"}
  return current
 from ai_foundation.auto_agent import AutoCapabilityAgent
 from ai_foundation.routed_agent_model import foundation_agent_model
 agent_model=foundation_agent_model(infer.router,infer.cloud_factory,infer.local_execution,tracer=tracer)
 search_available=bool(settings.choose_route('SEARCH'))
 # Optional first-party skill references are pinned to trusted release code.
 # A missing/tampered bundle disables only the skill tool, never daily chat.
 from ai_foundation.agent_skills import bundled_catalog
 import logging
 try:
  # Default off until the real 9B/A-B latency and daily-task E2E gate passes.
  # This toggle exposes reference text only, not an execution grant.
  skill_catalog=(bundled_catalog(Path(__file__).resolve().parents[1])
                 if os.getenv('AI_FOUNDATION_SKILLS_ENABLED','0')=='1' else None)
 except (OSError,ValueError,PermissionError) as exc:
  logging.getLogger('ai_foundation').warning('Agent Skills disabled: %s',type(exc).__name__)
  skill_catalog=None
 from ai_foundation.human_model_context import build_human_model_context
 def auto_agent_factory(request,run_id):
  personal=build_human_model_context(root/'human-model-bindings.json',request.owner_id,
      repository_root=Path(__file__).resolve().parents[1],guard=guard,run_id=run_id)
  selected_model=agent_model
  if personal is not None and personal.local_required:
   selected_model=foundation_agent_model(infer.router,infer.cloud_factory,infer.local_execution,tracer=tracer,local_required=True)
  return AutoCapabilityAgent(selected_model,capability_executor,request,search_available=search_available,run_id=run_id,human_model_context=personal,skill_catalog=skill_catalog)
 # Observation only, never owner/auth/approval proof
 auto_agent_factory._foundation_owner_humanmodel_factory = True
 # Retain the host-authenticated deterministic resolver, but do not
 # activate the unauthenticated legacy Kandev loopback question receiver in
 # the current owner's Operator. No Kandev dependency or default fallback.
 from ai_foundation.question_authority import CanonQuestionAuthority
 question_authority=CanonQuestionAuthority(root/'question-authority.json',Path(__file__).resolve().parents[1])
 # This is a callable only from a verified in-process host task producer.
 # The unauthenticated loopback question HTTP route intentionally cannot use it.
 from ai_foundation.host_question_review import resolve_host_question
 def host_question_resolver(bundle, authority):
  return resolve_host_question(
   bundle,authority,guard=guard,work_db=root/c.work_db,
   binding_path=root/'human-model-bindings.json',
   repository_root=Path(__file__).resolve().parents[1],
   deterministic_resolver=question_authority.resolve)
 # Read only the source-reviewed, disabled-by-default public research ledger.
 # Corrupt/missing input returns None; it never enables a model or service.
 from ai_foundation.harness_research_bootstrap import load_harness_research_ledger
 harness_research=load_harness_research_ledger(Path(__file__).resolve().parents[1])
 # This owner browser surface writes only exact explicit review documents;
 # model execution and MCP admission remain their existing separate boundaries.
 from m1_development_owner_review import OwnerDevelopmentReview
 from m1_development_ticket_factory import _owner_local_repo
 development_review=(OwnerDevelopmentReview(root,repo_factory=_owner_local_repo,work_db=c.work_db,storage_admission=storage_admission)
                     if os.getuid()==501 and os.geteuid()==501 else None)
 # KLM review is a lazy drill-down using this same owner Guard and installed
 # runtime contract. Normal review never adds a GitHub/network Canon lookup.
 klm_review=None
 if os.getuid()==501 and os.geteuid()==501:
  try:
   import hashlib
   from m1_klm_owner_review import OwnerKlmReview,PUBLIC_REVIEW_ERRORS
   runtime_root=Path(__file__).resolve().parents[1]
   review_contracts=('src/ai_foundation/guard.py','src/ai_foundation/klm_relation_review.py',
                    'src/ai_foundation/klm_review_source.py','scripts/m1_klm_owner_review.py',
                    'src/ai_foundation/operator_server.py','src/ai_foundation/klm_review_renderer.py')
   def review_fingerprint():
    h=hashlib.sha256(b'foundation-installed-klm-review/v1\0')
    for name in review_contracts:
     path=runtime_root/name
     if path.is_symlink() or not path.is_file():
      raise PermissionError('INSTALLED_KLM_CONTRACT_UNVERIFIED')
     raw=path.read_bytes()
     if not 0<len(raw)<=300000:
      raise PermissionError('INSTALLED_KLM_CONTRACT_UNVERIFIED')
     h.update(name.encode());h.update(b'\0');h.update(hashlib.sha256(raw).digest())
    return h.hexdigest()
   fingerprint=review_fingerprint()
   review_canon=CanonContract('installed-operator-klm-review','klm-host/v1:'+fingerprint)
   review_service=[None]
   review_service_lock=threading.Lock()
   def installed_klm_review():
    if review_fingerprint()!=fingerprint:
     raise PermissionError('INSTALLED_KLM_CONTRACT_CHANGED')
    with review_service_lock:
     if review_service[0] is None:
      review_service[0]=OwnerKlmReview.from_installed(root,guard=guard,canon=review_canon,
                                                   storage_admission=storage_admission)
     return review_service[0]
   installed_klm_review.public_errors=PUBLIC_REVIEW_ERRORS
   klm_review=installed_klm_review
  except (ImportError,OSError,ValueError):
   # A missing optional KLM binding never takes down the existing Operator.
   klm_review=None
 app=OperatorApplication(c,actions,settings=settings,reconciliation=ReconciliationService(actions,reconciliation_registry,verification_ports),local_compute=local_compute,inference=run_task,inference_dispatch=capability_executor,auto_agent_factory=auto_agent_factory,service_probes={'LOCAL COMPUTE':lambda:any(x.health=='ONLINE' for x in local_compute.candidates()),'PROVIDER REGISTRY':lambda:settings.preflight()['ok'],'TOOLHIVE FILES':lambda:composition is not None and composition.file_port._wait_running(timeout=1.0),'TOOLHIVE CODE':lambda:composition is not None and composition.repo_port is not None and composition.repo_port._wait_running(timeout=1.0),'LONG-TERM HEALTH':lambda:long_term_health.ok(stale_after=int(os.getenv('AI_FOUNDATION_LONG_TERM_HEALTH_STALE_SECONDS',str(long_term_health.interval*2))))},backup_dir=root.parent/'AI-Foundation-backup',update_stage=root.parent/'AI-Foundation-update-stage',activity=activity,chat_url=os.getenv('FOUNDATION_CHAT_URL',''),capability_factory=capability_factory,storage_admission=storage_admission,operational_notices=long_term_notices,tracer=tracer,question_resolver=None,question_authority=question_authority,host_question_resolver=host_question_resolver,mcp_owner_delegations=mcp_owner_delegations,research_ledger=harness_research,development_status=installed_development_status,development_review=development_review,klm_review=klm_review)
 app.guard_decision_wake=long_term_health.wake_maintenance
 app.capability_executor=capability_executor
 app.human_input=HumanInputService(app.intake.store,resume_waiting) if app.intake else None
 # Only after every canonical store has initialized successfully do we mark this
 # root established. Future restart then distinguishes first bootstrap from data loss.
 establish_authority_manifest(root,c)
 # Notification delivery is a side-effect observer, never part of core work authority.
 # Polling the canonical human projection also catches state changes from every producer.
 try:
  vapid=VapidCredentialStore(MacOSNativeCredentialStore()).load()
  push=PushDispatch(WebPushTransport(WebPushConfig(vapid.private_key,vapid.public_key,vapid.subject,root/'remote/push-subscriptions.json')),root/'remote/push-seen.json')
  def push_loop():
   # Notification delivery is bounded polling: one dispatch attempt per interval.
   # A broken transport must not become a tight failure loop or notification amplifier.
   interval=max(5,int(os.getenv('AI_FOUNDATION_WEBPUSH_SECONDS','5')))
   while True:
    try:push.dispatch(app.human_payload())
    except Exception:pass
    time.sleep(interval)
  threading.Thread(target=push_loop,name='foundation-webpush',daemon=True).start()
 except Exception:
  # Missing/broken notification credentials must not prevent the Operator from starting.
  pass
 # The HTTPS gateway needs a bounded, loopback-only CSRF readback.
 # Without this installed hook it falls back to rendering the heavy root
 # dashboard on EVERY mobile form submission and can time out even while
 # the Operator itself remains healthy.
 from ai_foundation.gateway_csrf import install_fast_csrf
 install_fast_csrf()
 server=serve(app,port=a.port)
 long_term_health.start()
 print(f'AI FOUNDATION operator: http://127.0.0.1:{server.server_port}/',flush=True); server.serve_forever()
if __name__=='__main__': main()

