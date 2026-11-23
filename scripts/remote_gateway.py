#!/usr/bin/env python3
"""TLS/auth gateway for the loopback Foundation Operator. No decision authority lives here."""
import argparse,http.client,json,os,ssl
from http.server import BaseHTTPRequestHandler
from ai_foundation.bounded_http import BoundedThreadingHTTPServer
from urllib.parse import parse_qs,urlparse,urlencode
from ai_foundation.remote_access import RemoteAccess,RemoteAccessConfig
try:
 from scripts.gateway_support import refresh_form_csrf
except ImportError:
 from gateway_support import refresh_form_csrf

def build_access():
 hosts=frozenset(x.strip().lower().rstrip('.') for x in os.environ.get('FOUNDATION_REMOTE_ALLOWED_HOSTS','').split(',') if x.strip())
 return RemoteAccess(RemoteAccessConfig(os.environ['FOUNDATION_REMOTE_SESSION_SECRET'],hosts,True))
MAX_UPSTREAM=2_000_000
_RELEASE_LINK_METADATA=frozenset({'utm_source','utm_medium','utm_campaign','utm_term','utm_content'})

def _release_get_query(raw):
 # A shared link can acquire UTM metadata without changing the release intent.
 # Keep the exact source SHA as the only business input; never pass metadata
 # into the signed Guard/Operator release render or any POST.
 if not isinstance(raw,str) or len(raw)>512:return None
 try:
  query=parse_qs(raw,keep_blank_values=True,strict_parsing=True,max_num_fields=6)
 except ValueError:return None
 if set(query)-(_RELEASE_LINK_METADATA|{'sha'}):return None
 if any(len(values)!=1 for values in query.values()):return None
 sha=query.get('sha',[''])[0]
 if len(sha)>128:return None
 for key in _RELEASE_LINK_METADATA & query.keys():
  val=query[key][0]
  if len(val)>128 or any(ord(ch)<32 or ord(ch)>126 for ch in val):
   return None
 if _RELEASE_LINK_METADATA & query.keys():
  # Never reflect an untrusted tracking value into a URL or HTML response.
  return sha,'/release'+('?' + urlencode({'sha':sha}) if 'sha' in query else '')
 return sha,None
# The browser sees HTTPS Tailscale Serve :8454; a verified loopback
# backend may receive a different Host port. Keep the exception narrow:
# same allowlisted ts.net name, exact 8454, live Serve owner and loopback.
_OWNER_SERVE_HTTPS_PORT=8454

def _owner_origin_allowed(access,origin,host,site,peer,*,trusted_serve):
 """Original exact Origin gate; never accept a different explicit Origin."""
 if not isinstance(origin,str) or not origin or (site or '').lower()=='cross-site':
  return False
 if access.origin_allowed(origin,host,site):
  return True
 if not trusted_serve or type(peer) is not str or not peer.startswith('serve-owner:'):
  return False
 name=host.rsplit(':',1)[0].lower()
 if (name not in access.config.allowed_hosts or not name.endswith('.ts.net')
     or not access.host_allowed(host)):
  return False
 return origin==f'https://{name}:{_OWNER_SERVE_HTTPS_PORT}'


def _release_referer_allowed(access,referer,host,site,peer,*,trusted_serve,path):
 """Narrow missing-Origin Android form recovery; never bypass a real Origin.

 The *only* exceptional case is the existing authenticated owner release UI.
 It requires a current Serve owner identity, loopback ingress, exact allowlisted
 HTTPS host:8454, Fetch-Site same-origin, and /release as the document URL.
 HMAC-bound form token and Guard authorization are checked separately.
 """
 if (not path.startswith('/release/') or not trusted_serve
     or type(peer) is not str or not peer.startswith('serve-owner:')
     or site!='same-origin' or type(referer) is not str
     or len(referer)>640):
  return False
 from urllib.parse import urlsplit
 try:
  parsed=urlsplit(referer)
  name=host.rsplit(':',1)[0].lower()
  allowed=(parsed.scheme=='https'
       and parsed.username is None and parsed.password is None
       and parsed.hostname==name
       and parsed.port==_OWNER_SERVE_HTTPS_PORT
       and not parsed.fragment
       and parsed.path=='/release'
       and name in access.config.allowed_hosts
       and name.endswith('.ts.net')
       and access.host_allowed(host))
 except (ValueError,TypeError):
  return False
 if not allowed:
  return False
 return _release_get_query(parsed.query) is not None


def _owner_origin_failure(access,origin,host,site,peer,*,trusted_serve,
                          path='',referer=None):
 """One fail-closed decision for the complete POST ingress.

 Other effectful endpoints still require their original exact Origin;
 only missing-Origin submissions from this service's own authenticated
 /release form can use the strictly proven same-origin Referer fallback.
 """
 if type(origin) is not str or not origin:
  if _release_referer_allowed(
    access,referer,host,site,peer,trusted_serve=trusted_serve,path=path):
   return None
  return 'ORIGIN_MISSING'
 if (site or '').lower()=='cross-site':
  return 'CROSS_SITE'
 if _owner_origin_allowed(access,origin,host,site,peer,trusted_serve=trusted_serve):
  return None
 from urllib.parse import urlsplit
 try:
  parsed=urlsplit(origin)
  scheme=parsed.scheme
  origin_name=parsed.hostname
  origin_port=parsed.port or (443 if scheme=='https' else 80)
 except (ValueError,TypeError):
  return 'ORIGIN_INVALID'
 if scheme!='https':
  return 'SCHEME_MISMATCH'
 expected_name=host.rsplit(':',1)[0].strip('[]').lower()
 if not origin_name or origin_name.lower()!=expected_name:
  return 'HOST_MISMATCH'
 if origin_port!=_OWNER_SERVE_HTTPS_PORT:
  return 'PORT_MISMATCH'
 if not trusted_serve or not peer.startswith('serve-owner:'):
  return 'SERVE_CONTEXT_UNVERIFIED'
 return 'ORIGIN_UNVERIFIED'


def _human_payload(upstream_port,timeout=5):
 c=http.client.HTTPConnection('127.0.0.1',upstream_port,timeout=timeout)
 try:
  c.request('GET','/api/human',headers={'Host':f'127.0.0.1:{upstream_port}'})
  r=c.getresponse();raw=r.read(MAX_UPSTREAM+1)
 finally:c.close()
 if r.status!=200:raise RuntimeError('upstream status')
 if len(raw)>MAX_UPSTREAM:raise ValueError('upstream payload too large')
 data=json.loads(raw)
 if not isinstance(data,dict):raise TypeError('payload must be object')
 notices=data.get('notices') or [];tasks=data.get('tasks') or []
 if not isinstance(notices,list) or not isinstance(tasks,list) or any(not isinstance(x,dict) for x in notices+tasks):raise TypeError('invalid collections')
 if 'state' not in data:raise TypeError('state missing')
 return data,raw

def handler(access,upstream_port,*,mobile_release=None,tailnet_owner=None):
 class H(BaseHTTPRequestHandler):
  def release_peer(self):
   if mobile_release is None or tailnet_owner is None:return None
   host=self.headers.get('Host','')
   name=host.rsplit(':',1)[0].strip('[]').lower()
   # The privileged path never accepts public ingress, bare IPs, DNS
   # rebinding, proxies or a Tailscale-shared/tagged non-owner peer.
   if (name not in access.config.allowed_hosts or not name.endswith('.ts.net')
       or not access.host_allowed(host)):return None
   direct=tailnet_owner.owner_peer(self.client_address[0])
   if direct:return direct
   # Serve terminates the actual phone connection and the upstream socket
   # sees 127.0.0.1, not the original Tailscale peer. A browser-supplied
   # identity header is NEVER privileged on an externally bound gateway.
   if (os.environ.get('FOUNDATION_REMOTE_SERVE_OWNER_ENABLED')!='1'
       or self.server.server_address[0]!='127.0.0.1'
       or self.client_address[0]!='127.0.0.1'):
    return None
   matching=[(key,val) for key,val in self.headers.items()
             if key.lower().replace('_','-')=='tailscale-user-login']
   if (len(matching)!=1
       or matching[0][0].lower()!='tailscale-user-login'):
    return None
   return tailnet_owner.serve_owner_login(matching[0][1])
  def proxy_operator(self,method,path,body=None):
   c=http.client.HTTPConnection('127.0.0.1',upstream_port,timeout=130)
   headers={'Host':f'127.0.0.1:{upstream_port}'}
   try:
    if body is not None:
     body=refresh_form_csrf(body,upstream_port)
     headers['Content-Type']='application/x-www-form-urlencoded'
    c.request(method,path,body=body,headers=headers);r=c.getresponse();data=r.read(MAX_UPSTREAM+1)
    if len(data)>MAX_UPSTREAM:return self.sendb(502,b'{"error":"upstream response too large"}\n')
    # Forward the original Operator document unchanged. Do not inject a
    # second release/approval link into the existing owner dashboard.
    extra=()
    if r.getheader('Location'):extra=(('Location',r.getheader('Location')),)
    return self.sendb(r.status,data,r.getheader('Content-Type','text/html; charset=utf-8'),extra)
   except (OSError,http.client.HTTPException,RuntimeError,ValueError,UnicodeDecodeError):return self.sendb(503,b'{"error":"foundation unavailable"}\n')
   finally:c.close()
  def sendb(self,code,body=b'',ctype='application/json; charset=utf-8',extra=(),release_page=False):
   self.send_response(code);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');self.send_header('Referrer-Policy','same-origin' if release_page else 'no-referrer');self.send_header('Strict-Transport-Security','max-age=31536000');self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=()');self.send_header('Cross-Origin-Opener-Policy','same-origin');self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; script-src " + ("'none'" if release_page else "'unsafe-inline'") + "; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
   for k,v in extra:self.send_header(k,v)
   self.end_headers();self.wfile.write(body)
  def allowed(self):
   return access.host_allowed(self.headers.get('Host',''))
  def do_GET(self):
   if not self.allowed():return self.sendb(400,b'{"error":"host rejected"}\n')
   path=urlparse(self.path).path
   if path=='/release':
    peer=self.release_peer()
    if not peer:return self.sendb(403,b'{"error":"mobile owner unavailable"}\n')
    parsed=_release_get_query(urlparse(self.path).query)
    if parsed is None:
     return self.sendb(400,b'{"error":"invalid release query"}\n')
    sha,canonical=parsed
    if canonical is not None:
     # Drop only bounded URL-campaign metadata; never grant or infer approval.
     # Redirect is relative and happens after actual live owner verification.
     return self.sendb(303,extra=(('Location',canonical),),release_page=True)
    code,page=mobile_release.render(peer,sha)
    return self.sendb(code,page.encode(),'text/html; charset=utf-8',release_page=True)
   if path=='/health':
    try:
     data,raw=_human_payload(upstream_port,2)
    except (OSError,http.client.HTTPException,RuntimeError,ValueError,json.JSONDecodeError):
     return self.sendb(503,b'{"ok":false,"upstream":false}\\n')
    return self.sendb(200,b'{"ok":true,"upstream":true}\\n')
   if path=='/':return self.proxy_operator('GET',self.path)
   # The existing responsive Operator page fetches these live read-only
   # projections. They used to fail with 404 on the HTTPS/mobile ingress.
   if path in ('/echo','/presentation/theme','/api/human/status',
               '/api/human/echo/status','/api/human/notices',
               '/api/provider-services','/api/harness-services'):
    return self.proxy_operator('GET',self.path)
   # Review pages contain owner-private CODE/KLM metadata: a mere allowed
   # Tailnet Host is not sufficient. Require live same-owner WhoIs per GET.
   if path in ('/development/review','/klm/review'):
    if not self.release_peer():
     return self.sendb(403,b'{"error":"owner review unavailable"}\n')
    return self.proxy_operator('GET',self.path)
   if path=='/api/human':
    try:
     data,body=_human_payload(upstream_port)
    except (OSError,http.client.HTTPException,RuntimeError,ValueError,TypeError,json.JSONDecodeError):
     return self.sendb(503,b'{"error":"foundation unavailable"}\\n')
    return self.sendb(200,body,'application/json; charset=utf-8')
   return self.sendb(404,b'not found\n','text/plain; charset=utf-8')
  def do_POST(self):
   """Complete owner POST routing: one identity, origin, size and token boundary."""
   if not self.allowed():
    return self.sendb(400,b'{"error":"host rejected"}\n')
   peer=self.release_peer()
   if not peer:
    return self.sendb(403,b'{"error":"owner verification unavailable"}\n')
   path=urlparse(self.path).path
   site=self.headers.get('Sec-Fetch-Site')
   trusted_serve=(os.environ.get('FOUNDATION_REMOTE_SERVE_OWNER_ENABLED')=='1'
       and self.server.server_address[0]=='127.0.0.1'
       and self.client_address[0]=='127.0.0.1')
   reason=_owner_origin_failure(
    access,self.headers.get('Origin'),self.headers.get('Host',''),
    site,peer,trusted_serve=trusted_serve,path=path,
    referer=self.headers.get('Referer'))
   if reason is not None:
    return self.sendb(403,(
      '{"error":"owner origin rejected","reason":"'+reason+'"}\n').encode())
   if self.headers.get('Transfer-Encoding'):
    return self.sendb(411,b'{"error":"content-length required"}\n')
   try:
    n=int(self.headers.get('Content-Length','0'))
   except ValueError:
    return self.sendb(400,b'{"error":"invalid request"}\n')
   if n<0 or n>8192:
    return self.sendb(413,b'{"error":"request too large"}\n')
   if path.startswith('/release/'):
    if (self.headers.get('Content-Type','').split(';')[0].strip().lower()
        !='application/x-www-form-urlencoded'):
     return self.sendb(403,b'{"error":"owner origin rejected","reason":"CONTENT_TYPE_UNSUPPORTED"}\n')
    if n>2048:
     return self.sendb(413,b'{"error":"release request too large"}\n')
   body=self.rfile.read(n)
   if path.startswith('/release/'):
    try:
     form=parse_qs(body.decode('utf-8'),keep_blank_values=True)
    except UnicodeDecodeError:
     return self.sendb(400,b'{"error":"invalid release form"}\n')
    if path=='/release/probe-post':
     code,page=mobile_release.verify_transport(peer,form)
    else:
     action=path.rsplit('/',1)[-1]
     code,page=mobile_release.submit(action,peer,form)
    return self.sendb(code,page.encode(),'text/html; charset=utf-8',release_page=True)
   owner_paths=('/development/review/','/development/delegation/',
                '/klm/review/')
   if any(path.startswith(prefix) for prefix in owner_paths):
    return self.proxy_operator('POST',path,body)
   allowed=(path.startswith('/settings/')
       or path.startswith('/presentation/theme/')
       or path.startswith('/notification/dismiss/')
       or path.startswith('/action/'))
   if not allowed:
    return self.sendb(404,b'not found\n','text/plain; charset=utf-8')
   return self.proxy_operator('POST',path,body)
  def log_message(self,*a):pass
 return H
def main():
 p=argparse.ArgumentParser();p.add_argument('--listen',default='0.0.0.0');p.add_argument('--port',type=int,default=8793);p.add_argument('--upstream-port',type=int,default=8766);p.add_argument('--cert',required=True);p.add_argument('--key',required=True);a=p.parse_args()
 access=build_access()
 mobile_release=tailnet_owner=None
 mode=os.environ.get('FOUNDATION_REMOTE_MOBILE_RELEASE_ENABLED','auto')
 if mode not in ('auto','0','1'):
  raise SystemExit('INVALID_MOBILE_RELEASE_MODE')
 # Trusted Tailscale Serve identity requires an owner-controlled gateway
 # lifecycle that binds only localhost; reject an unsafe startup rather than
 # silently accepting forwarded caller identity on a remotely exposed socket.
 proxy_mode=os.environ.get('FOUNDATION_REMOTE_SERVE_OWNER_ENABLED','0')
 if proxy_mode not in ('0','1'):
  raise SystemExit('INVALID_REMOTE_SERVE_OWNER_MODE')
 if proxy_mode=='1' and a.listen!='127.0.0.1':
  raise SystemExit('REMOTE_SERVE_OWNER_REQUIRES_LOOPBACK_BIND')
 # The existing HTTPS Tailnet gateway may expose this owner-requested view
 # only as the original M1 owner and with an explicitly configured ts.net
 # name. '0' disables it; neither arbitrary LAN/public peers nor a model can
 # gain execution authority from enabling presentation code.
 private_name=any(name.endswith('.ts.net') for name in access.config.allowed_hosts)
 if mode!='0' and private_name and os.getuid()==os.geteuid()==501:
  from scripts.m1_mobile_owner_release import MobileOwnerRelease,TailnetOwnerIdentity
  mobile_release=MobileOwnerRelease(access.config.session_secret)
  tailnet_owner=TailnetOwnerIdentity()
 srv=BoundedThreadingHTTPServer(
  (a.listen,a.port),handler(access,a.upstream_port,
    mobile_release=mobile_release,tailnet_owner=tailnet_owner))
 ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.minimum_version=ssl.TLSVersion.TLSv1_2
 ctx.load_cert_chain(a.cert,a.key);srv.socket=ctx.wrap_socket(srv.socket,server_side=True);srv.serve_forever()
if __name__=='__main__':main()
