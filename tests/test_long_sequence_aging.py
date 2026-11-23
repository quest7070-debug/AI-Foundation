import json,random,sqlite3,threading,time
import pytest
from ai_foundation.settings_service import SettingsService
from ai_foundation.provider_onboarding import ProbeResult
from ai_foundation.durable_inference import SQLiteInferenceAttemptStore
from ai_foundation.inference_port import CloudInferencePort,InferenceResultStore
from ai_foundation.core import TaskPlan
from ai_foundation.notification_boundary import project_push
from ai_foundation.notification_dismissal import NotificationDismissals

class Secrets:
 def __init__(self):self.d={}
 def save(self,b,s):self.d[b]=s
 def load(self,b):return self.d[b]
 def delete(self,b):return self.d.pop(b,None) is not None
 def available(self,b):return b in self.d
class Probe:
 def probe(self,s,h=None):return ProbeResult(h or 'GROQ','ONLINE',80,'1m',70,'1d')

def _svc(root):return SettingsService(root,Probe(),Secrets())

def test_legal_provider_operation_sequence_keeps_routes_within_live_free_authority(tmp_path):
 s=Secrets();x=SettingsService(tmp_path,Probe(),s);rnd=random.Random(7070);keys=[]
 for step in range(180):
  op=rnd.randrange(5)
  if op==0 and len(keys)<5:
   key='gsk_'+f'{step:024d}';x.add_provider(key);keys.append(key)
  elif op==1 and x.registry.bindings():x.refresh_provider(rnd.choice(x.registry.bindings()))
  elif op==2:x.optimize_all_routes()
  elif op==3 and x.registry.bindings():
   b=rnd.choice(x.registry.bindings());x.remove_provider(b)
  else:
   # Restart against the same durable DB/secret authority.
   x=SettingsService(tmp_path,Probe(),s)
  live={r['binding'] for r in x.credentials() if r['tier']=='FREE' and r['health']=='ONLINE'}
  for route in x.routes():
   assert all(b in live or b.startswith('local:') for b in ((route.primary,) if route.primary else ())+route.standby)
  assert x.preflight()['ok']

def test_malformed_persistent_route_isolated_to_that_route_not_registry(tmp_path):
 s=Secrets();x=SettingsService(tmp_path,Probe(),s);x.add_provider('gsk_'+'A'*24);b=x.registry.bindings()[0]
 with sqlite3.connect(tmp_path/'routing.sqlite') as db:db.execute("UPDATE routes SET ordered_bindings='not-json' WHERE function='SEARCH'")
 restarted=SettingsService(tmp_path,Probe(),s)
 assert restarted.registry.credential(b)['health']=='ONLINE'
 assert restarted.route('SEARCH').primary is None and restarted.route('SEARCH').standby==()
 assert restarted.route('CHAT').primary==b

def test_verified_inference_replay_survives_many_redeliveries_and_restart(tmp_path):
 class E:
  def __init__(self):self.calls=0
  def invoke(self,b,p):self.calls+=1;return 'once'
 e=E();p=TaskPlan('r','compute','llm',text='x',effect_id='stable-id');path=tmp_path/'a.db'
 CloudInferencePort(e,'b',InferenceResultStore(),'CHAT',SQLiteInferenceAttemptStore(path)).execute(p)
 for _ in range(100):
  out=InferenceResultStore();CloudInferencePort(e,'b',out,'CHAT',SQLiteInferenceAttemptStore(path)).execute(p);assert out.get('stable-id')=='once'
 assert e.calls==1

def test_delayed_complete_cannot_overwrite_newer_verified_result(tmp_path):
 s=SQLiteInferenceAttemptStore(tmp_path/'a.db');s.get_or_begin('r','b');assert s.complete('r','new').result=='new'
 # A delayed duplicate completion is ignored by the conditional DISPATCHING update.
 assert s.complete('r','old').result=='new'

def test_concurrent_refresh_optimize_remove_never_leaves_removed_binding_in_route(tmp_path):
 s=Secrets();x=SettingsService(tmp_path,Probe(),s);x.add_provider('gsk_'+'B'*24);b=x.registry.bindings()[0];errs=[];start=threading.Barrier(3)
 def refresh():
  start.wait()
  for _ in range(50):
   try:x.refresh_provider(b)
   except KeyError:return
   except Exception as e:errs.append(e);return
 def optimize():
  start.wait()
  for _ in range(50):
   try:x.optimize_all_routes()
   except Exception as e:errs.append(e);return
 t1=threading.Thread(target=refresh);t2=threading.Thread(target=optimize);t1.start();t2.start();start.wait();x.remove_provider(b);t1.join();t2.join()
 assert not errs and x.registry.credential(b) is None
 assert all(b not in (((r.primary,) if r.primary else ())+r.standby) for r in x.routes())

def test_default_authority_remains_narrow_after_repeated_restart(tmp_path):
 s=Secrets();x=SettingsService(tmp_path,Probe(),s);x.registry.upsert('paid','GROQ','PAID','ONLINE',100,'x',100,'y',endpoint='https://x',model='m',protocol='openai-chat',capabilities=('CHAT','PC_CONTROL','FILES'))
 for _ in range(20):
  x=SettingsService(tmp_path,Probe(),s);x.optimize_all_routes()
  assert x.route('CHAT').primary is None and x.route('PC_CONTROL').primary is None and x.route('FILES').primary is None

def test_notification_dedup_is_transition_scoped_and_dismissal_does_not_hide_new_state(tmp_path):
 p=lambda st:{'notices':[{'level':4,'kind':'work','subject':'job','status':st,'summary_ja':st}]}
 first=project_push(p('FAILED'));assert len(first)==1
 seen=frozenset({first[0].key});assert project_push(p('FAILED'),seen)==()
 assert len(project_push(p('WAITING_HUMAN'),seen))==1
 d=NotificationDismissals(tmp_path/'w.db');d.dismiss('job','FAILED');assert d.hidden('job','FAILED') and not d.hidden('job','WAITING_HUMAN')

def test_large_operator_projection_is_bounded_and_escapes_long_names(tmp_path):
 from ai_foundation.operator_server import OperatorApplication
 from ai_foundation.human_operations import HumanNotice
 from ai_foundation.human_view import from_snapshot
 from ai_foundation.human_renderer import render
 class C:data_dir=str(tmp_path);work_db='w.db'
 class A:pass
 class Snap:
  def as_dict(self):return {'ready':True,'waiting_human':0,'effects':{},'attention':[]}
 class Settings:
  def cards(self):return ()
  def routes(self):return ()
  def credentials(self):return ()
 app=OperatorApplication(C(),A(),settings=Settings(),operational_notices=lambda:tuple(HumanNotice(3,'system',f'n{i}','FAILED','X'*80+'<script>','D'*80,False,False,float(i)) for i in range(500)))
 app.snapshot=lambda:Snap();payload=app.human_payload()
 assert len(payload['notices'])==500 and payload['severity_counts'][2]==500
 # Render a representative large visible slice; the canonical snapshot itself already caps DB attention at 100.
 notices=tuple(HumanNotice(3,'system',f'n{i}','FAILED','X'*80+'<script>','D'*80) for i in range(100))
 page=render(from_snapshot(Snap(),notices=notices),'responsive')
 assert 'X'*80+'&lt;script&gt;' in page and 'X'*80+'<script>' not in page and 'overflow-wrap:anywhere' in page
