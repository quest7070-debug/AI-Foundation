#!/usr/bin/env python3
import argparse,json,uuid
from pathlib import Path
from ai_foundation.shadow import ShadowObservation,append_evidence,h3_report,EvidenceClass

def observation(path,status='VERIFIED_COMPLETE',verification='VERIFIED',output='ok',route_kind=None,route_label=None):
 return ShadowObservation(path,route_kind,route_label,status,verification,output)

def record(path,evidence,candidate,baseline):
 append_evidence(evidence,candidate,baseline,EvidenceClass.LIVE if path in {'local-inference','cloud-inference'} else EvidenceClass.ISOLATED_REAL)

def run_local(evidence):
 from ai_foundation.llama_swap_adapter import LlamaSwapExecution
 token='FOUNDATION_H3_'+uuid.uuid4().hex[:10]
 prompt='Reply with exactly: '+token
 output=LlamaSwapExecution().chat(prompt).strip()
 # Current-backend evidence is a live contract assertion, not a fake comparison
 # against the retired AI Home Server. Baseline is the requested exact token.
 baseline=observation('local-inference',output=token,route_kind='LOCAL',route_label='llama-swap / local-general')
 candidate=observation('local-inference',output=output,route_kind='LOCAL',route_label='llama-swap / local-general')
 record('local-inference',evidence,candidate,baseline)
 return output==token


def run_cloud(evidence):
 from ai_foundation.productization import load_config
 from ai_foundation.settings_service import SettingsService
 from ai_foundation.provider_probe import LiveProviderProbe
 from ai_foundation.http_transport import UrllibCloudTransport
 from ai_foundation.native_credentials import MacOSNativeCredentialStore
 from ai_foundation.cloud_execution import ObservedCloudExecution
 from ai_foundation.provider_observer import ProviderResponseObserver
 from ai_foundation.core import TaskPlan,CanonContract
 from ai_foundation.guard import GuardCore
 from ai_foundation.core import GuardState
 from ai_foundation.compute_routing import ComputeRouter
 from ai_foundation.local_compute_registry import LocalComputeRegistry
 from ai_foundation.llama_swap_adapter import LlamaSwapDiscovery,LlamaSwapExecution
 from ai_foundation.inference_service import GuardedInferenceService
 import os
 config=load_config(os.environ.get('AI_FOUNDATION_CONFIG',str(Path.home()/'.config/ai-foundation/config.json')))
 root=Path(config.data_dir);transport=UrllibCloudTransport()
 settings=SettingsService(root,LiveProviderProbe(transport),MacOSNativeCredentialStore(),local_compute=LocalComputeRegistry(LlamaSwapDiscovery()))
 settings.optimize_all_routes()
 route=settings.route('CHAT')
 cloud=next((b for b in ((route.primary,) if route.primary else ())+route.standby if b.startswith('llm:')),None)
 if not cloud:return False
 token='FOUNDATION_H3_CLOUD_'+uuid.uuid4().hex[:10]
 plan=TaskPlan('h3-cloud-'+uuid.uuid4().hex,'compute','llm',text='Reply with exactly: '+token,canon_revision='h3',effect_id='h3-cloud-'+uuid.uuid4().hex)
 router=ComputeRouter(settings,LocalComputeRegistry(LlamaSwapDiscovery()))
 execution=ObservedCloudExecution(settings.registry,settings.secret_store,ProviderResponseObserver(settings.registry),transport)
 service=GuardedInferenceService(GuardCore(GuardState()),router,LlamaSwapExecution(),cloud_factory=lambda _:execution)
 out=service.run(plan,CanonContract('h3','h3'),'CHAT')
 label=settings.route_label(out.route_binding) if out.route_binding else None
 candidate=observation('cloud-inference',status=out.status,verification='VERIFIED' if out.status=='VERIFIED_COMPLETE' else out.status,output=(out.result or '').strip(),route_kind=out.route_kind,route_label=label)
 baseline=observation('cloud-inference',output=token,route_kind='CLOUD',route_label=label)
 record('cloud-inference',evidence,candidate,baseline)
 return out.status=='VERIFIED_COMPLETE' and out.route_kind=='CLOUD' and (out.result or '').strip()==token

def run_toolhive(evidence,root):
 from ai_foundation.toolhive import ToolHiveFilesystemPort
 from ai_foundation.core import TaskPlan
 thv=Path(__file__).parents[1]/'.tools/toolhive/thv'; mount=Path('/tmp/ai-foundation-toolhive')
 if not thv.exists() or not mount.exists(): return False
 target=mount/('h3-evidence-'+uuid.uuid4().hex+'.txt'); content='H3_TOOL_'+uuid.uuid4().hex
 port=ToolHiveFilesystemPort(thv,'ai-foundation-fs',mount)
 plan=TaskPlan('h3-'+uuid.uuid4().hex,'write',str(target),text=content,canon_revision='h3')
 port.execute(plan); observed=port.observe(plan); host=target.read_text(); target.unlink(missing_ok=True)
 b=observation('tool-effect',output=host)
 c=observation('tool-effect',output=observed)
 record('tool-effect',evidence,c,b)
 return observed==host==content


def run_uncertain(evidence):
 from ai_foundation.toolhive import ToolHiveFilesystemPort
 from ai_foundation.core import TaskPlan,CanonContract
 from ai_foundation.guard import GuardCore
 from ai_foundation.store import SQLiteGuardStore
 import tempfile
 thv=Path(__file__).parents[1]/'.tools/toolhive/thv'; mount=Path('/tmp/ai-foundation-toolhive')
 if not thv.exists() or not mount.exists(): return False
 target=mount/('h3-uncertain-'+uuid.uuid4().hex+'.txt'); content='H3_UNCERTAIN_'+uuid.uuid4().hex
 base=ToolHiveFilesystemPort(thv,'ai-foundation-fs',mount)
 class Lost:
  def __init__(self): self.count=0
  def execute(self,plan): self.count+=1;base.execute(plan);raise ConnectionError('simulated lost response')
  def observe(self,plan): return base.observe(plan)
 with tempfile.TemporaryDirectory() as td:
  store=SQLiteGuardStore(Path(td)/'g.db');plan=TaskPlan('h3-u-'+uuid.uuid4().hex,'write',str(target),text=content,canon_revision='h3',exclusive_target=True)
  lost=Lost(); first=GuardCore(store.load(),100,store).execute(plan,CanonContract('h3','h3'),lost,content)
  if first!='UNCERTAIN_RECONCILE_REQUIRED' or lost.count!=1:return False
  class ObserveOnly(ToolHiveFilesystemPort):
   def execute(self,plan): raise AssertionError('recovery must never re-execute')
  # Reconstruct Guard from durable state, then reconcile only by independent readback.
  recovered=GuardCore(store.load(),100,store).reconcile_effect(plan.run_id,plan,ObserveOnly(thv,'ai-foundation-fs',mount))
  host=target.read_text(); target.unlink(missing_ok=True)
  baseline=observation('uncertain-recovery',output=host)
  candidate=observation('uncertain-recovery',output=host if recovered=='VERIFIED_COMPLETE' else recovered)
  record('uncertain-recovery',evidence,candidate,baseline)
  return recovered=='VERIFIED_COMPLETE' and host==content and lost.count==1


def run_cancellation(evidence):
 import tempfile,threading
 from ai_foundation.toolhive import ToolHiveFilesystemPort
 from ai_foundation.core import TaskPlan,CanonContract
 from ai_foundation.guard import GuardCore
 from ai_foundation.store import SQLiteGuardStore
 thv=Path(__file__).parents[1]/'.tools/toolhive/thv'; mount=Path('/tmp/ai-foundation-toolhive')
 if not thv.exists() or not mount.exists(): return False
 target=mount/('h3-cancel-'+uuid.uuid4().hex+'.txt'); content='H3_CANCEL_'+uuid.uuid4().hex
 base=ToolHiveFilesystemPort(thv,'ai-foundation-fs',mount); started=threading.Event();release=threading.Event()
 class Delayed:
  def __init__(self):self.count=0
  def execute(self,p):self.count+=1;base.execute(p);started.set();release.wait(5)
  def observe(self,p):return base.observe(p)
 with tempfile.TemporaryDirectory() as td:
  store=SQLiteGuardStore(Path(td)/'g.db');plan=TaskPlan('h3-c-'+uuid.uuid4().hex,'write',str(target),text=content,canon_revision='h3',exclusive_target=True)
  port=Delayed();out=[];g=GuardCore(store.load(),100,store)
  t=threading.Thread(target=lambda:out.append(g.execute(plan,CanonContract('h3','h3'),port,content)));t.start()
  if not started.wait(5):return False
  GuardCore(store.load(),100,store).cancel(plan.run_id);release.set();t.join(5)
  host=target.read_text();status=store.load().effects[plan.run_id].status.value
  # Durable cancellation must block a blind retry; explicit reconciliation is a separate authority path.
  retry=GuardCore(store.load(),100,store).execute(plan,CanonContract('h3','h3'),port,content)
  target.unlink(missing_ok=True)
  ok=out==['CANCELLED_RECONCILE_REQUIRED'] and port.count==1 and status=='UNCERTAIN' and retry=='DENY' and host==content
  baseline=observation('cancellation',status='CANCELLED_RECONCILE_REQUIRED',verification='UNCERTAIN',output=content)
  candidate=observation('cancellation',status=out[0] if out else 'FAILED',verification=status,output=host)
  append_evidence(evidence,candidate,baseline,EvidenceClass.ISOLATED_REAL)
  return ok


def run_approval(evidence):
 import tempfile
 from ai_foundation.store import SQLiteGuardStore
 from ai_foundation.guard import GuardCore
 from ai_foundation.operator_actions import OperatorActions
 with tempfile.TemporaryDirectory() as td:
  path=Path(td)/'g.db';run='h3-a-'+uuid.uuid4().hex;store=SQLiteGuardStore(path)
  if run in store.load().approvals:return False
  if not OperatorActions(GuardCore(store.load(),100,store)).approve_run(run).ok:return False
  # Reconstruct authority from disk: approval must survive and be the same run only.
  state=SQLiteGuardStore(path).load(); ok=run in state.approvals and len(state.approvals)==1
  b=observation('human-approval',status='APPROVED',verification='DURABLE',output=run)
  c=observation('human-approval',status='APPROVED' if ok else 'FAILED',verification='DURABLE' if ok else 'FAILED',output=run)
  append_evidence(evidence,c,b,EvidenceClass.DETERMINISTIC);return ok

def run_human_input(evidence):
 import tempfile
 from ai_foundation.task_intake import TaskIntake
 from ai_foundation.human_input import HumanInputService
 class Waiting: status='WAITING_HUMAN';result=None
 class Done: status='VERIFIED_COMPLETE';result='accepted';route_kind='LOCAL';route_binding='local-general'
 with tempfile.TemporaryDirectory() as td:
  db=Path(td)/'w.db';intake=TaskIntake(db);r=intake.submit('needs human context')
  if intake.execute(r.job_id,lambda _:Waiting())!='WAITING_HUMAN':return False
  first=HumanInputService(intake.store,lambda *_:(_ for _ in ()).throw(RuntimeError('resume lost')))
  if first.respond(r.job_id+':0','answer').status!='INPUT_RECORDED_RESUME_FAILED':return False
  reopened=TaskIntake(db); seen=[]
  def resume(job,pos):
   seen.append(reopened.store.pending_human_input(job,pos))
   out=reopened.execute(job,lambda _:Done())
   if reopened.store.load(job)[pos].status.value=='VERIFIED':reopened.store.consume_human_input(job,pos)
   return out
  # Resume existing durable input without submitting a second answer.
  out=resume(r.job_id,0);row=reopened.store.load(r.job_id)[0]
  ok=seen==['answer'] and out=='accepted' and row.status.value=='VERIFIED' and reopened.store.pending_human_input(r.job_id,0) is None
  b=observation('human-input',output='accepted');c=observation('human-input',output='accepted' if ok else 'failed')
  append_evidence(evidence,c,b,EvidenceClass.DETERMINISTIC);return ok

def run_failover(evidence):
 import tempfile
 from ai_foundation.settings_service import SettingsService
 from ai_foundation.provider_onboarding import ProbeResult
 class Secrets:
  def save(self,*x):pass
  def load(self,b):return 'fixture-'+b
  def available(self,b):return True
  def delete(self,b):return True
 class Probe:
  def probe(self,*x):return ProbeResult('GROQ','ONLINE',80,'1m',70,'1d')
 with tempfile.TemporaryDirectory() as td:
  x=SettingsService(Path(td),Probe(),Secrets());x.registry.upsert('primary','GROQ','FREE','ONLINE',90,'s',80,'l',endpoint='https://x',model='m',protocol='openai-chat',capabilities=('CHAT','CODE'));x.registry.upsert('standby','MISTRAL','FREE','ONLINE',70,'s',60,'l',endpoint='https://x',model='m',protocol='openai-chat',capabilities=('CHAT','CODE'));x.optimize_all_routes()
  before=(x.route().primary,x.choose_route());x.registry.observe('primary',health='DOWN',active=False,reason='HTTP 503');down=(x.route().primary,x.choose_route())
  # Reconstruct SettingsService to prove persisted policy order + live health survive process restart.
  y=SettingsService(Path(td),Probe(),Secrets());after_restart=(y.route().primary,y.choose_route());y.registry.observe('primary',health='ONLINE',active=False,reason='recovered');preopt=(y.route().primary,y.choose_route());y.optimize_routing('CHAT');recovered=(y.route().primary,y.choose_route())
  # Startup optimization may persist the healthy standby as primary while the former primary is DOWN. Recovery restores eligibility immediately, but route preference changes only at the explicit optimizer boundary.
  ok=before==('primary','primary') and down==('primary','standby') and after_restart==('standby','standby') and preopt==('standby','standby') and recovered==('primary','primary')
  expected='primary>standby>standby>standby>primary';actual='>'.join((before[1],down[1],after_restart[1],preopt[1],recovered[1]))
  b=observation('provider-failover',output=expected);c=observation('provider-failover',output=actual)
  append_evidence(evidence,c,b,EvidenceClass.DETERMINISTIC);return ok

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--evidence',required=True);ap.add_argument('--path',choices=['local-inference','cloud-inference','tool-effect','uncertain-recovery','cancellation','human-approval','human-input','provider-failover','report'],required=True);a=ap.parse_args()
 evidence=Path(a.evidence);evidence.parent.mkdir(parents=True,exist_ok=True)
 if a.path=='local-inference': ok=run_local(evidence)
 elif a.path=='cloud-inference': ok=run_cloud(evidence)
 elif a.path=='tool-effect': ok=run_toolhive(evidence,evidence.parent)
 elif a.path=='uncertain-recovery': ok=run_uncertain(evidence)
 elif a.path=='cancellation': ok=run_cancellation(evidence)
 elif a.path=='human-approval': ok=run_approval(evidence)
 elif a.path=='human-input': ok=run_human_input(evidence)
 elif a.path=='provider-failover': ok=run_failover(evidence)
 else:
  rows=h3_report(evidence,{'cloud-inference':'valid credential not intentionally available'})
  print(json.dumps([r.__dict__ for r in rows],indent=2));return
 if not ok: raise SystemExit('evidence scenario mismatch')
 print(a.path,'evidence recorded')
if __name__=='__main__':main()
