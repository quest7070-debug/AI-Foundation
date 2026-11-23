from ai_foundation.presentation import PresentationPreferences
def test_presentation_preference_is_only_theme_and_atomic(tmp_path):
 p=PresentationPreferences(tmp_path/'presentation.json');assert p.get()=='I';p.set('C');assert p.get()=='C'
 try:p.set('X');assert False
 except ValueError:pass
 assert p.get()=='C'

def test_operator_theme_switch_persists_without_operational_state(tmp_path):
 import threading,urllib.request,urllib.parse
 from ai_foundation.operator_server import OperatorApplication,serve
 class C:data_dir=str(tmp_path);work_db='w.db'
 class A:pass
 class S:
  def as_dict(self):return {'ready':True,'waiting_human':0,'effects':{},'attention':[]}
 app=OperatorApplication(C(),A(),csrf_token='T');app.snapshot=lambda:S();srv=serve(app);threading.Thread(target=srv.serve_forever,daemon=True).start()
 try:
  base=f'http://127.0.0.1:{srv.server_port}';assert 'content="I"' in urllib.request.urlopen(base+'/').read().decode()
  req=urllib.request.Request(base+'/presentation/theme/toggle',data=urllib.parse.urlencode({'csrf':'T'}).encode(),method='POST');urllib.request.urlopen(req)
  assert 'content="C"' in urllib.request.urlopen(base+'/mobile').read().decode()
  import json;assert json.loads((tmp_path/'presentation.json').read_text())=={'theme':'C'}
 finally:srv.shutdown();srv.server_close()

def test_theme_switch_redirects_back_to_ui_and_visual_tokens_are_distinct(tmp_path):
 import threading,urllib.request,urllib.parse,re
 from ai_foundation.operator_server import OperatorApplication,serve
 class C:data_dir=str(tmp_path);work_db='w.db'
 class A:pass
 class S:
  def as_dict(self):return {'ready':True,'waiting_human':0,'effects':{},'attention':[]}
 app=OperatorApplication(C(),A(),csrf_token='T');app.snapshot=lambda:S();srv=serve(app);threading.Thread(target=srv.serve_forever,daemon=True).start()
 try:
  base=f'http://127.0.0.1:{srv.server_port}'
  req=urllib.request.Request(base+'/presentation/theme/toggle',data=urllib.parse.urlencode({'csrf':'T'}).encode(),headers={'Referer':base+'/'},method='POST')
  page=urllib.request.urlopen(req).read().decode()
  assert 'content="C"' in page and 'background:#101310' in page and 'background:#202520' in page
 finally:srv.shutdown();srv.server_close()
