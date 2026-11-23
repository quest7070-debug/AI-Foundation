import json,threading,urllib.request,urllib.error
from ai_foundation.core import EffectIntent,EffectStatus,TaskPlan
from ai_foundation.guard import GuardCore
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.operator_server import OperatorApplication,serve
from ai_foundation.productization import FoundationConfig
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.reconciliation_registry import SQLiteReconciliationRegistry,ReconciliationService
class ObserveOnly:
 def __init__(self,v):self.v=v;self.execs=0;self.obs=0
 def execute(self,p):self.execs+=1;raise AssertionError('must not execute')
 def observe(self,p):self.obs+=1;return self.v
def post(url,token):
 req=urllib.request.Request(url,data=('csrf='+token).encode(),method='POST',headers={'Content-Type':'application/x-www-form-urlencoded','Host':url.split('/')[2]})
 try:
  with urllib.request.urlopen(req) as r:return r.status,json.loads(r.read())
 except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
def test_restart_http_reconcile_uncertain_to_verified(tmp_path):
 root=tmp_path/'data';root.mkdir();c=FoundationConfig(str(root.resolve()));store=SQLiteGuardStore(root/c.guard_db);state=store.load();state.effects['e1']=EffectIntent('e1','r1','target','DONE',EffectStatus.UNCERTAIN);store.save(state)
 reg=SQLiteReconciliationRegistry(root/c.reconciliation_db);reg.register('e1',TaskPlan('r1','write','target',effect_id='e1'),'verify:test')
 # restart: reconstruct Guard, registry and verification port from durable state/binding
 port=ObserveOnly('DONE');guard=GuardCore(SQLiteGuardStore(root/c.guard_db).load(),store=SQLiteGuardStore(root/c.guard_db));actions=OperatorActions(guard);svc=ReconciliationService(actions,SQLiteReconciliationRegistry(root/c.reconciliation_db),{'verify:test':port})
 app=OperatorApplication(c,actions,csrf_token='TOKEN',reconciliation=svc);srv=serve(app);t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
 try:
  base=f'http://127.0.0.1:{srv.server_port}';html=urllib.request.urlopen(base+'/').read().decode();assert 'VERIFY OUTCOME' not in html and '結果未確定・既存の独立読戻しで照合が必要です' in html and '外部作用の結果を確定できません' in html
  code,payload=post(base+'/action/reconcile/e1','TOKEN');assert code==200 and payload['status']=='VERIFIED_COMPLETE';assert port.execs==0 and port.obs==1
  html2=urllib.request.urlopen(base+'/').read().decode();assert '外部作用の結果を確定できません' not in html2;assert SQLiteGuardStore(root/c.guard_db).load().effects['e1'].status is EffectStatus.VERIFIED
 finally:srv.shutdown();srv.server_close()
def test_restart_http_missing_port_fails_closed(tmp_path):
 root=tmp_path/'data';root.mkdir();c=FoundationConfig(str(root.resolve()));store=SQLiteGuardStore(root/c.guard_db);st=store.load();st.effects['e']=EffectIntent('e','r','t','x',EffectStatus.UNCERTAIN);store.save(st);reg=SQLiteReconciliationRegistry(root/c.reconciliation_db);reg.register('e',TaskPlan('r','write','t',effect_id='e'),'gone')
 g=GuardCore(SQLiteGuardStore(root/c.guard_db).load(),store=SQLiteGuardStore(root/c.guard_db));a=OperatorActions(g);app=OperatorApplication(c,a,csrf_token='T',reconciliation=ReconciliationService(a,reg,{}));srv=serve(app);threading.Thread(target=srv.serve_forever,daemon=True).start()
 try:code,p=post(f'http://127.0.0.1:{srv.server_port}/action/reconcile/e','T');assert code==409 and p['status']=='VERIFICATION_PORT_UNAVAILABLE';assert SQLiteGuardStore(root/c.guard_db).load().effects['e'].status is EffectStatus.UNCERTAIN
 finally:srv.shutdown();srv.server_close()
