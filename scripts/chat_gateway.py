#!/usr/bin/env python3
import argparse,http.client,hmac,hashlib,time,sys
from http.server import BaseHTTPRequestHandler
from ai_foundation.bounded_http import BoundedThreadingHTTPServer
try:
 from scripts.gateway_support import current_csrf
except ImportError:
 from gateway_support import current_csrf
ALLOWED={'/v1/models','/v1/chat/completions'};MAX=2*1024*1024
TRUSTED=('X-Foundation-Attachments','X-Foundation-Owner','X-Foundation-Capability','X-Foundation-Scope','X-Foundation-Long-Running','X-Foundation-Attachment-Timestamp','X-Foundation-Attachment-Signature')
def _foundation_verification(src,secret,body=b'',now=None):
 present=any(src.get(k,'') for k in TRUSTED)
 if not present:return {},'absent'
 if not secret:return {},'rejected:no-secret'
 vals={k:src.get(k,'') for k in TRUSTED}
 owner=vals['X-Foundation-Owner'];raw_ids=vals['X-Foundation-Attachments'];cap=(vals['X-Foundation-Capability'] or 'CHAT').upper();scope=vals['X-Foundation-Scope'];long_running=vals['X-Foundation-Long-Running']
 if not owner or not vals['X-Foundation-Attachment-Timestamp'] or not vals['X-Foundation-Attachment-Signature']:return {},'rejected:incomplete'
 try:
  import json
  ts=int(vals['X-Foundation-Attachment-Timestamp']);ids=json.loads(raw_ids or '[]')
 except (ValueError,TypeError,json.JSONDecodeError):return {},'rejected:malformed'
 if abs(int(time.time() if now is None else now)-ts)>60:return {},'rejected:stale'
 if len(owner)>256 or cap not in {'CHAT','SEARCH','CODE','DATA','FILES','PC_CONTROL','VISION'} or len(scope)>128 or long_running not in {'','0','1'}:return {},'rejected:authority'
 if not isinstance(ids,list) or len(ids)>10:return {},'rejected:attachments'
 if any(not isinstance(x,str) or not x or len(x)>256 for x in ids) or len(set(ids))!=len(ids):return {},'rejected:attachments'
 canonical=json.dumps(ids,separators=(',',':'))
 if raw_ids and raw_ids!=canonical:return {},'rejected:canonicalization'
 digest=hashlib.sha256(body or b'').hexdigest()
 msg=('v2\n'+owner+'\n'+canonical+'\n'+cap+'\n'+scope+'\n'+('1' if long_running=='1' else '0')+'\n'+str(ts)+'\n'+digest).encode()
 expected=hmac.new(secret.encode(),msg,hashlib.sha256).hexdigest()
 if not hmac.compare_digest(expected,vals['X-Foundation-Attachment-Signature']):return {},'rejected:signature'
 out={'X-Foundation-Owner':owner,'X-Foundation-Capability':cap,'X-Foundation-Attachment-Timestamp':str(ts)}
 if canonical!='[]':out['X-Foundation-Attachments']=canonical
 if scope:out['X-Foundation-Scope']=scope
 if long_running=='1':out['X-Foundation-Long-Running']='1'
 return out,'verified'

def _verified_attachment_headers(src,secret,body=b'',now=None):
 return _foundation_verification(src,secret,body,now)[0]

def _audit_verification(result):
 print(f'foundation.trust {result}',file=sys.stderr,flush=True)

class H(BaseHTTPRequestHandler):
 def _proxy(self):
  if self.path not in ALLOWED:self.send_error(404);return
  n=int(self.headers.get('Content-Length','0') or 0)
  if n<0 or n>MAX:self.send_error(413);return
  body=self.rfile.read(n) if n else None;c=http.client.HTTPConnection('127.0.0.1',self.server.upstream,timeout=130);headers={}
  try:
   if body is not None:
    headers={'Content-Type':'application/json','X-Foundation-CSRF':current_csrf(self.server.upstream)}
    verified,verification=_foundation_verification(self.headers,getattr(self.server,'attachment_secret',''),body or b'')
    _audit_verification(verification)
    headers.update(verified)
   c.request(self.command,self.path,body=body,headers=headers);r=c.getresponse();data=r.read(MAX+1)
   if len(data)>MAX:raise ValueError('upstream too large')
   self.send_response(r.status);self.send_header('Content-Type',r.getheader('Content-Type','application/json'));self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
  except Exception:self.send_error(502)
  finally:c.close()
 def do_GET(self):self._proxy()
 def do_POST(self):self._proxy()
 def log_message(self,*a):pass
class S(BoundedThreadingHTTPServer):pass

def _load_attachment_secret(binding='foundation:attachment-handoff'):
 if not binding:return ''
 try:
  from ai_foundation.native_credentials import MacOSNativeCredentialStore
  return MacOSNativeCredentialStore().load(binding)
 except (KeyError,OSError,RuntimeError):
  return ''

def serve(host,port,upstream,csrf=None,attachment_secret=None,attachment_binding='foundation:attachment-handoff'):
 if host not in {'127.0.0.1','0.0.0.0'}:raise ValueError('unsupported host')
 secret=_load_attachment_secret(attachment_binding) if attachment_secret is None else attachment_secret
 server=S((host,port),H);server.upstream=upstream;server.attachment_secret=secret;return server
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--host',default='0.0.0.0');p.add_argument('--port',type=int,default=8767);p.add_argument('--upstream',type=int,default=8766);p.add_argument('--csrf',required=False);p.add_argument('--attachment-binding',default='foundation:attachment-handoff');a=p.parse_args();serve(a.host,a.port,a.upstream,a.csrf,attachment_binding=a.attachment_binding).serve_forever()
