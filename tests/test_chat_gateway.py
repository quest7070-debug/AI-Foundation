import threading,urllib.request,json
from scripts.chat_gateway import serve
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
class U(BaseHTTPRequestHandler):
 def do_GET(self):
  b=(b'<input name=csrf value="secret">' if self.path=='/' else b'{"data":[]}' );self.send_response(200);self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
 def do_POST(self):
  assert self.headers['X-Foundation-CSRF']=='secret';b=b'{"choices":[]}';self.send_response(200);self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
 def log_message(self,*a):pass
def test_gateway_allowlist_and_csrf():
 u=ThreadingHTTPServer(('127.0.0.1',0),U);threading.Thread(target=u.serve_forever,daemon=True).start();g=serve('127.0.0.1',0,u.server_port,'secret',attachment_secret='');threading.Thread(target=g.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{g.server_port}'
 try:
  assert json.load(urllib.request.urlopen(base+'/v1/models'))=={'data':[]}
  req=urllib.request.Request(base+'/v1/chat/completions',data=b'{}',headers={'Content-Type':'application/json'});assert json.load(urllib.request.urlopen(req))=={'choices':[]}
  try:urllib.request.urlopen(base+'/api/human');assert False
  except urllib.error.HTTPError as e:assert e.code==404
 finally:g.shutdown();u.shutdown();g.server_close();u.server_close()

def test_attachment_headers_require_valid_fresh_hmac():
 import time
 from scripts.chat_gateway import _verified_attachment_headers
 owner='u1';attachments='["f1"]';body=b'{"model":"foundation-auto"}';ts=int(time.time());secret='s'
 headers=_signed_v2(secret,body,owner=owner,ids=attachments,cap='CHAT',ts=ts)
 out=_verified_attachment_headers(headers,secret,body,ts)
 assert out['X-Foundation-Owner']==owner and out['X-Foundation-Attachments']==attachments
 assert _verified_attachment_headers(headers|{'X-Foundation-Attachment-Signature':'0'*64},secret,body,ts)=={}
 assert _verified_attachment_headers(headers,secret,body,ts+61)=={}
 assert _verified_attachment_headers(headers,secret,b'changed',ts)=={}
 assert _verified_attachment_headers(headers,'',body,ts)=={}
 for bad in ('not-json','["f1","f1"]','['+','.join('"f%d"'%i for i in range(11))+']'):
  badh=headers|{'X-Foundation-Attachments':bad}
  assert _verified_attachment_headers(badh,secret,body,ts)=={}

def test_attachment_secret_loads_from_native_store(monkeypatch):
 import scripts.chat_gateway as g
 class Store:
  def load(self,binding):
   assert binding=='foundation:attachment-handoff'
   return 'native-secret'
 import ai_foundation.native_credentials as nc
 monkeypatch.setattr(nc,'MacOSNativeCredentialStore',lambda:Store())
 assert g._load_attachment_secret()=='native-secret'

def test_attachment_secret_missing_fails_closed(monkeypatch):
 import scripts.chat_gateway as g
 class Store:
  def load(self,binding): raise KeyError(binding)
 import ai_foundation.native_credentials as nc
 monkeypatch.setattr(nc,'MacOSNativeCredentialStore',lambda:Store())
 assert g._load_attachment_secret()==''

def _signed_v2(secret,body,owner='u1',ids='[]',cap='SEARCH',scope='',long='0',ts=100):
 import hmac,hashlib
 msg=f'v2\n{owner}\n{ids}\n{cap}\n{scope}\n{long}\n{ts}\n{hashlib.sha256(body).hexdigest()}'.encode()
 return {'X-Foundation-Owner':owner,'X-Foundation-Attachments':ids,'X-Foundation-Capability':cap,'X-Foundation-Scope':scope,'X-Foundation-Long-Running':long,'X-Foundation-Attachment-Timestamp':str(ts),'X-Foundation-Attachment-Signature':hmac.new(secret.encode(),msg,hashlib.sha256).hexdigest()}

def test_signed_capability_metadata_is_body_bound_and_fail_closed():
 from scripts.chat_gateway import _verified_attachment_headers
 body=b'{}';h=_signed_v2('s',body,cap='CODE',scope='project-a',long='1')
 out=_verified_attachment_headers(h,'s',body,100)
 assert out['X-Foundation-Capability']=='CODE' and out['X-Foundation-Scope']=='project-a' and out['X-Foundation-Long-Running']=='1'
 assert _verified_attachment_headers(h|{'X-Foundation-Capability':'FILES'},'s',body,100)=={}
 assert _verified_attachment_headers(h,'s',b'{"changed":1}',100)=={}
 assert _verified_attachment_headers(_signed_v2('s',body,cap='BAD'),'s',body,100)=={}


def test_foundation_verification_distinguishes_absent_rejected_and_verified_without_secrets(capsys):
 import time
 from scripts.chat_gateway import _foundation_verification,_audit_verification
 body=b'{"model":"foundation-auto"}';secret='never-log-this-secret';ts=int(time.time())
 assert _foundation_verification({},secret,body,ts)==({},'absent')
 bad=_signed_v2(secret,body,cap='CHAT',ts=ts)|{'X-Foundation-Attachment-Signature':'0'*64}
 assert _foundation_verification(bad,secret,body,ts)[1]=='rejected:signature'
 good=_signed_v2(secret,body,cap='CHAT',ts=ts)
 headers,status=_foundation_verification(good,secret,body,ts)
 assert status=='verified' and headers['X-Foundation-Capability']=='CHAT'
 for state in ('absent','rejected:signature','verified'):_audit_verification(state)
 logged=capsys.readouterr().err
 assert logged.splitlines()==[
  'foundation.trust absent',
  'foundation.trust rejected:signature',
  'foundation.trust verified',
 ]
 assert secret not in logged
 assert good['X-Foundation-Attachment-Signature'] not in logged

def test_foundation_verification_rejection_reasons_are_bounded():
 from scripts.chat_gateway import _foundation_verification
 body=b'{}';secret='s'
 cases=[
  ({'X-Foundation-Capability':'CHAT'},'rejected:incomplete'),
  (_signed_v2(secret,body,ts=100)|{'X-Foundation-Attachment-Timestamp':'x'},'rejected:malformed'),
  (_signed_v2(secret,body,ts=100),'rejected:stale'),
  (_signed_v2(secret,body,cap='BAD',ts=200),'rejected:authority'),
  (_signed_v2(secret,body,ids='["f1","f1"]',ts=200),'rejected:attachments'),
 ]
 for headers,expected in cases:
  assert _foundation_verification(headers,secret,body,200 if expected!='rejected:stale' else 161)[1]==expected

def test_signed_vision_capability_is_preserved_by_gateway_authority_boundary():
    import time
    from scripts.chat_gateway import _verified_attachment_headers

    body=b'{"model":"foundation-vision","messages":[{"role":"user","content":"describe"}]}'
    ts=int(time.time())
    h=_signed_v2(
        's',
        body,
        owner='u1',
        ids='["vision-file"]',
        cap='VISION',
        ts=ts,
    )

    out=_verified_attachment_headers(h,'s',body,ts)

    assert out['X-Foundation-Owner']=='u1'
    assert out['X-Foundation-Attachments']=='["vision-file"]'
    assert out['X-Foundation-Capability']=='VISION'
