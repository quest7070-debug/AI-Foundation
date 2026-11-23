import json,threading,urllib.request
from ai_foundation.operator_server import OperatorApplication,serve
class C:data_dir='/tmp';work_db='human-api-test.sqlite'
class A:pass
def test_human_api_is_foundation_semantics_not_legacy_proxy(monkeypatch):
 app=OperatorApplication(C(),A())
 monkeypatch.setattr(app,'snapshot',lambda:type('S',(),{'as_dict':lambda self:{'ready':True,'attention':[{'kind':'work','id':'j:0','job_id':'j','step':'ask','status':'WAITING_HUMAN','updated_at':1}],'waiting_human':1,'work':{'WAITING_HUMAN':1}}})())
 monkeypatch.setattr('ai_foundation.operator_server.human_tasks',lambda _i:())
 srv=serve(app);threading.Thread(target=srv.serve_forever,daemon=True).start()
 try:
  r=urllib.request.urlopen(f'http://127.0.0.1:{srv.server_port}/api/human'); d=json.loads(r.read())
  assert d['state']=='WAITING_HUMAN' and d['notices'][0]['subject']=='j:0'
  assert d['notices'][0]['input_required'] and not d['notices'][0]['actionable']
  assert r.headers['Cache-Control']=='no-store'
 finally:srv.shutdown();srv.server_close()

def test_human_api_notification_counts_match_visible_notices_after_dismissal(tmp_path):
 import urllib.parse
 class TC:data_dir=str(tmp_path);work_db='w.db'
 class Snap:
  def as_dict(self):
   return {'ready':True,'attention':[
    {'kind':'effect','id':'u','status':'UNCERTAIN','updated_at':3},
    {'kind':'approval','id':'a','run_id':'a','status':'WAITING_HUMAN','updated_at':2},
    {'kind':'work','id':'f:0','status':'FAILED','updated_at':1},
   ],'waiting_human':1,'work':{'FAILED':1,'WAITING_HUMAN':1},'effects':{'UNCERTAIN':1}}
 app=OperatorApplication(TC(),A(),csrf_token='T');app.snapshot=lambda:Snap()
 srv=serve(app);threading.Thread(target=srv.serve_forever,daemon=True).start()
 try:
  base=f'http://127.0.0.1:{srv.server_port}'
  d=json.loads(urllib.request.urlopen(base+'/api/human').read())
  assert d['severity_counts']==[0,0,1,1,1]
  assert [(n['status'],n['level']) for n in d['notices']]==[('UNCERTAIN',5),('WAITING_HUMAN',4),('FAILED',3)]
  page=urllib.request.urlopen(base+'/').read().decode()
  assert 'LV5 CRITICAL' in page and 'LV4 ACTION' in page and 'LV3 ATTENTION' in page
  assert '<b class="ui-metric">1<small>LV5 CRITICAL</small></b>' in page
  assert '<b class="ui-metric">1<small>LV4 ACTION</small></b>' in page
  assert '<b class="ui-metric">1<small>LV3 ATTENTION</small></b>' in page
  req=urllib.request.Request(base+'/notification/dismiss/f:0',data=urllib.parse.urlencode({'csrf':'T'}).encode(),method='POST')
  urllib.request.urlopen(req)
  d=json.loads(urllib.request.urlopen(base+'/api/human').read())
  assert d['severity_counts']==[0,0,0,1,1] and len(d['notices'])==2
  assert app.snapshot().as_dict()['work']['FAILED']==1
 finally:srv.shutdown();srv.server_close()
