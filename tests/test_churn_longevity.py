import sqlite3
from pathlib import Path
from ai_foundation.settings_service import SettingsService
from ai_foundation.provider_onboarding import ProbeResult
from ai_foundation.llama_swap_adapter import LlamaSwapDiscovery
from ai_foundation.notification_dismissal import NotificationDismissals
from ai_foundation.task_intake import TaskIntake
from ai_foundation.orchestration import WorkStatus
from ai_foundation.attachment_handoff import AttachmentHandoff,AttachmentRecord

class Secrets:
 def __init__(self):self.d={}
 def save(self,b,s):self.d[b]=s
 def load(self,b):return self.d[b]
 def delete(self,b):return self.d.pop(b,None) is not None
 def available(self,b):return b in self.d
class Probe:
 def probe(self,s,h=None):return ProbeResult(h or 'GROQ','ONLINE',80,'1m',70,'1d')

def test_provider_add_replace_refresh_remove_2000_cycles_converges(tmp_path):
 sec=Secrets();svc=SettingsService(tmp_path,Probe(),sec)
 for n in range(2000):
  svc.add_provider(f'TEST_PROVIDER_TOKEN_{n}',provider='GROQ');b=svc.registry.bindings()[0]
  svc.replace_provider_credential(b,f'TEST_PROVIDER_REPLACED_{n}');svc.refresh_provider(b);svc.remove_provider(b)
 assert svc.registry.bindings()==() and sec.d=={}
 assert all(r.primary is None and r.standby==() for r in svc.routes())
 assert svc.cards()==() and svc.preflight()['ok']

def test_local_model_inventory_3000_replacements_has_no_stale_aliases(tmp_path):
 manifest=tmp_path/'llama.yaml';state={'rows':[]}
 class R:
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def read(self,n):
   import json;return json.dumps({'data':state['rows']}).encode()
 def opener(*a,**k):return R()
 d=LlamaSwapDiscovery(opener=opener,manifest_path=manifest)
 for n in range(3000):
  alias='local-general' if n%2 else 'local-code-agent';state['rows']=[{'id':alias,'status':{'value':'ready'}}]
  rows=d();assert len(rows)==1 and rows[0].slot==alias
 state['rows']=[];rows=d();assert len(rows)==1 and rows[0].health=='UNAVAILABLE' and rows[0].capabilities==()

def test_notification_and_terminal_task_churn_converges_without_actionable_growth(tmp_path):
 p=tmp_path/'work.db';intake=TaskIntake(p);dismiss=NotificationDismissals(p)
 for n in range(3000):
  r=intake.submit(f'task {n}');intake.store.set(r.job_id,0,WorkStatus.VERIFIED,'ok');dismiss.dismiss(r.job_id,'VERIFIED')
 assert intake.purge_terminal()==3000 and intake.recent(20)==[]
 with sqlite3.connect(p) as db:
  assert db.execute('select count(*) from work_steps').fetchone()[0]==0
  assert db.execute('select count(*) from task_intake').fetchone()[0]==0
  # Dismissal rows are derived UI cache and disappear with their purged terminal jobs.
  assert db.execute('select count(*) from notification_dismissals').fetchone()[0]==0

def test_attachment_use_delete_failure_churn_converges_owner_scoped(tmp_path,monkeypatch):
 root=tmp_path/'uploads';root.mkdir();records={}
 def lookup(a,o):return records.get((o,a))
 h=AttachmentHandoff(root,lookup)
 for n in range(2000):
  owner=f'u{n%7}';aid=f'a{n}';records[(owner,aid)]=AttachmentRecord(aid,owner,text=f'value {n}')
  grant=h.resolve(owner,[aid])[0];assert Path(grant.path).read_text()==f'value {n}'
  assert h.acquire(grant);h.release(grant);records.pop((owner,aid));h.reconcile_upstream()
 assert list(h.handoff_root.glob('*'))==[]
 # Materialization failure leaves neither published authority nor temp fragments.
 records[('u','bad')]=AttachmentRecord('bad','u',text='x')
 original=Path.write_text;calls={'n':0}
 def fail_second(self,*a,**k):
  calls['n']+=1
  if calls['n']==2:raise OSError('simulated metadata write failure')
  return original(self,*a,**k)
 monkeypatch.setattr(Path,'write_text',fail_second)
 try:h.resolve('u',['bad'])
 except OSError:pass
 else:raise AssertionError('failure expected')
 assert not list(h.handoff_root.glob('*.tmp')) and not list(h.handoff_root.glob('*.meta.tmp'))

def test_mcp_schema_replace_remove_3000_cycles_never_executes_ghost_tool(monkeypatch):
 import subprocess,json,pytest
 from ai_foundation.toolhive import ToolHiveMCPClient,BoundMCPTools
 generation={'n':0};calls=[]
 def fake(argv,**kw):
  if argv[2]=='list':
   n=generation['n'];return subprocess.CompletedProcess(argv,0,json.dumps({'tools':([{'name':f't{n}','inputSchema':{'type':'object'}}] if n%3 else [])}),'')
  calls.append(tuple(argv));return subprocess.CompletedProcess(argv,0,json.dumps({'content':[]}),'')
 monkeypatch.setattr(subprocess,'run',fake);c=ToolHiveMCPClient('/thv','server-a')
 previous=None
 for n in range(3000):
  generation['n']=n;name=f't{n}';bound=BoundMCPTools(c,{name});inv=bound.inventory()
  if n%3:assert set(inv)=={name}
  else:assert inv=={}
  if previous is not None:
   with pytest.raises((PermissionError,ValueError)):BoundMCPTools(c,{previous}).call(previous,{})
  previous=name
 assert calls==[]
