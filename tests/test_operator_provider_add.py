import io
from ai_foundation.operator_server import OperatorApplication,make_handler,serve
class Actions: pass
class Config: data_dir='/tmp'; work_db='x.sqlite'
class Settings:
 def __init__(self): self.seen=None
 def add_provider(self,key,provider,tier): self.seen=(key,provider,tier); return {'provider':'GROQ','tier':tier,'credentials':1,'health':'ONLINE'}
def test_page_has_password_provider_form_and_never_embeds_key(monkeypatch):
 s=Settings(); app=OperatorApplication(Config(),Actions(),csrf_token='tok',settings=s)
 monkeypatch.setattr(app,'snapshot',lambda:type('S',(),{'as_dict':lambda self:{'ready':True,'attention':[],'waiting_human':0}})())
 page=app.page()
 assert ('type="password"' in page or "type='password'" in page)
 assert '/settings/provider/add' in page and 'api_key' in page
 assert 'SUPERSECRET' not in page

def test_provider_add_form_round_trip_preserves_reserved_key_characters(monkeypatch):
 import threading,urllib.parse,urllib.request
 from ai_foundation.operator_server import serve
 s=Settings(); app=OperatorApplication(Config(),Actions(),csrf_token='tok',settings=s)
 monkeypatch.setattr(app,'snapshot',lambda:type('S',(),{'as_dict':lambda self:{'ready':True,'attention':[],'waiting_human':0}})())
 srv=serve(app); threading.Thread(target=srv.serve_forever,daemon=True).start()
 try:
  key='gsk_A+B/C=D_abcdefghijklmnopqrstuvwxyz'
  body=urllib.parse.urlencode({'csrf':'tok','api_key':key,'provider':'GROQ','tier':'FREE'}).encode()
  req=urllib.request.Request(f'http://127.0.0.1:{srv.server_port}/settings/provider/add',data=body,method='POST')
  with urllib.request.urlopen(req) as response: assert response.status==201
  assert s.seen==(key,'GROQ','FREE')
 finally:srv.shutdown();srv.server_close()

class SelectionSettings(Settings):
 def add_provider(self,key,provider,tier): raise ValueError('provider selection required')

def test_auto_detection_failure_returns_renderer_owned_selection_state(monkeypatch):
 import threading,urllib.parse,urllib.request,urllib.error
 app=OperatorApplication(Config(),Actions(),csrf_token='tok',settings=SelectionSettings())
 monkeypatch.setattr(app,'snapshot',lambda:type('S',(),{'as_dict':lambda self:{'ready':True,'attention':[],'waiting_human':0}})())
 srv=serve(app);threading.Thread(target=srv.serve_forever,daemon=True).start()
 try:
  body=urllib.parse.urlencode({'csrf':'tok','api_key':'unknown-key','provider':'','tier':'FREE','return_to':'/'}).encode();req=urllib.request.Request(f'http://127.0.0.1:{srv.server_port}/settings/provider/add',data=body,method='POST')
  class NoRedirect(urllib.request.HTTPRedirectHandler):
   def redirect_request(self,*args,**kwargs): return None
  try:urllib.request.build_opener(NoRedirect).open(req)
  except urllib.error.HTTPError as e:
   assert e.code==303 and e.headers['Location']=='/?provider_error=selection_required#settings'
  page=app.page()
  assert '<details id="provider-options">' in page and 'THIS KEY HAS NO SAFE PROVIDER SIGNATURE' in page
 finally:srv.shutdown();srv.server_close()
