import threading,urllib.request,urllib.parse,json
from ai_foundation.operator_server import OperatorApplication,serve
class C:data_dir='/tmp';work_db='x.sqlite'
class A:pass
class S:
 def cards(self):return ()
 def routes(self):return ()
 def credentials(self):return ({'binding':'cred-1','provider':'GROQ','tier':'FREE','health':'ONLINE','short_remaining':80,'long_remaining':70,'active':False,'reason':None},)
 def route_label(self,x):return x
 def remove_provider(self,b):self.removed=b;return {'removed':True,'provider':'GROQ','tier':'FREE'}
def test_delete_credential_action_and_no_raw_secret():
 s=S();app=OperatorApplication(C(),A(),csrf_token='T',settings=s);app.snapshot=lambda:type('X',(),{'as_dict':lambda self:{'ready':True,'attention':[],'waiting_human':0,'effects':{}}})()
 page=app.page();assert 'REMOVE' in page and 'cred-1' not in page and 'api-secret' not in page
 srv=serve(app);threading.Thread(target=srv.serve_forever,daemon=True).start()
 try:
  token=app.credential_token('cred-1');req=urllib.request.Request(f'http://127.0.0.1:{srv.server_port}/settings/provider/remove/{token}',data=urllib.parse.urlencode({'csrf':'T'}).encode(),method='POST');assert json.loads(urllib.request.urlopen(req).read())['removed'];assert s.removed=='cred-1'
 finally:srv.shutdown();srv.server_close()

def test_credential_controls_include_refresh_update_delete_without_raw_binding():
 s=S();app=OperatorApplication(C(),A(),csrf_token='T',settings=s);app.snapshot=lambda:type('X',(),{'as_dict':lambda self:{'ready':True,'attention':[],'waiting_human':0,'effects':{}}})()
 page=app.page(); assert 'CHECK' in page and 'CHANGE KEY' in page and 'REMOVE' in page and 'cred-1' not in page
