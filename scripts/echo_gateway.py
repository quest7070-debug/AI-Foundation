#!/usr/bin/env python3
import argparse,http.client
from http.server import BaseHTTPRequestHandler
from ai_foundation.bounded_http import BoundedThreadingHTTPServer
try:
 from scripts.gateway_support import current_csrf,refresh_form_csrf
except ImportError:
 from gateway_support import current_csrf,refresh_form_csrf
MAX=2*1024*1024
def allowed(method,path):
 if method=='GET': return path in {'/echo','/presentation/theme','/api/human'}
 if method=='POST': return path=='/presentation/theme/toggle' or path.startswith('/notification/dismiss/')
 return False
class H(BaseHTTPRequestHandler):
 def _proxy(self):
  if not allowed(self.command,self.path):self.send_error(404);return
  n=int(self.headers.get('Content-Length','0') or 0)
  if n<0 or n>MAX:self.send_error(413);return
  body=self.rfile.read(n) if n else None
  if body is not None: body=refresh_form_csrf(body,self.server.upstream)
  c=http.client.HTTPConnection('127.0.0.1',self.server.upstream,timeout=130)
  headers={}
  if body is not None:
   headers['Content-Type']=self.headers.get('Content-Type','application/x-www-form-urlencoded')
   headers['X-Foundation-CSRF']=current_csrf(self.server.upstream)
  try:
   c.request(self.command,self.path,body=body,headers=headers);r=c.getresponse();data=r.read(MAX+1)
   if len(data)>MAX:raise ValueError('upstream too large')
   self.send_response(r.status);self.send_header('Content-Type',r.getheader('Content-Type','application/json'));self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');loc=r.getheader('Location'); loc and self.send_header('Location', 'http://127.0.0.1:8788'+loc if loc.startswith('/') else loc);self.end_headers();self.wfile.write(data)
  except Exception:self.send_error(502)
  finally:c.close()
 def do_GET(self):self._proxy()
 def do_POST(self):self._proxy()
 def log_message(self,*a):pass
class S(BoundedThreadingHTTPServer):pass
def serve(host,port,upstream,csrf):
 if host not in {'127.0.0.1','0.0.0.0'}:raise ValueError('unsupported host')
 s=S((host,port),H);s.upstream=upstream;return s
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8788);p.add_argument('--upstream',type=int,default=8766);p.add_argument('--csrf',required=False);a=p.parse_args();serve(a.host,a.port,a.upstream,a.csrf).serve_forever()
