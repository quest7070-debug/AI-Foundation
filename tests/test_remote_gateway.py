import http.client,threading
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from scripts.remote_gateway import handler
from ai_foundation.remote_access import RemoteAccess,RemoteAccessConfig

class U(BaseHTTPRequestHandler):
 def do_GET(self):
  b=(b'<html><input name=csrf value="T"><section id="settings">SETTINGS</section><section id="development">DEVELOPMENT</section>'+self.path.encode()+b'</html>') if self.path.startswith('/') and not self.path.startswith('/api/') else b'{"state":"READY","notices":[],"tasks":[]}'
  self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
 def do_POST(self):
  n=int(self.headers.get('Content-Length','0'));self.rfile.read(n);b=b'OK';self.send_response(200);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b)
 def log_message(self,*x):pass

def setup(owner=False,release=None):
 from types import SimpleNamespace
 hostname='owner-m1.example.ts.net' if owner else 'remote.test'
 a=RemoteAccess(RemoteAccessConfig('S'*48,frozenset({hostname}),owner))
 u=ThreadingHTTPServer(('127.0.0.1',0),U);threading.Thread(target=u.serve_forever,daemon=True).start()
 if owner:
  proof=SimpleNamespace(owner_peer=lambda _ip:'verified-owner-node')
  h=handler(a,u.server_port,mobile_release=release if release is not None else object(),tailnet_owner=proof)
 else:
  h=handler(a,u.server_port)
 g=ThreadingHTTPServer(('127.0.0.1',0),h);threading.Thread(target=g.serve_forever,daemon=True).start()
 return a,u,g

def test_stable_root_is_real_operator_without_browser_session():
 a,u,g=setup()
 try:
  c=http.client.HTTPConnection('127.0.0.1',g.server_port);c.request('GET','/',headers={'Host':'remote.test'});r=c.getresponse();assert r.status==200 and b'SETTINGS' in r.read()
 finally:g.shutdown();u.shutdown();g.server_close();u.server_close()

def test_owner_dashboard_never_injects_a_second_release_approval_link():
 a,u,g=setup(owner=True)
 try:
  c=http.client.HTTPConnection('127.0.0.1',g.server_port,timeout=5)
  c.request('GET','/',headers={'Host':'owner-m1.example.ts.net:8793'})
  r=c.getresponse();html=r.read()
  assert r.status==200
  assert b'SETTINGS' in html
  assert b'href="/release"' not in html
  assert b'/action/delegate-mcp/' not in html
 finally:
  g.shutdown();u.shutdown();g.server_close();u.server_close()


def test_root_query_is_preserved_for_operator_feedback():
 a,u,g=setup()
 try:
  c=http.client.HTTPConnection('127.0.0.1',g.server_port);c.request('GET','/?provider_error=selection_required',headers={'Host':'remote.test'});r=c.getresponse();body=r.read();assert r.status==200 and b'provider_error=selection_required' in body
 finally:g.shutdown();u.shutdown();g.server_close();u.server_close()

def test_authenticated_same_origin_mutations_proxy_but_unknown_paths_fail():
 a,u,g=setup(owner=True)
 try:
  c=http.client.HTTPConnection('127.0.0.1',g.server_port)
  h={'Host':'owner-m1.example.ts.net:8793',
     'Origin':'https://owner-m1.example.ts.net:8793',
     'Content-Type':'application/x-www-form-urlencoded'}
  for path in ('/settings/routing/optimize','/presentation/theme/toggle',
               '/notification/dismiss/x','/action/cancel/x','/action/approve/x'):
   c.request('POST',path,'x=1',h);r=c.getresponse();assert r.status==200;r.read()
  c.request('POST','/evil','x=1',h);r=c.getresponse();assert r.status==404;r.read()
  for origin in ('https://attacker.test','http://owner-m1.example.ts.net:8793'):
   c.request('POST','/action/approve/x','x=1',{**h,'Origin':origin})
   r=c.getresponse();assert r.status==403;r.read()
 finally:g.shutdown();u.shutdown();g.server_close();u.server_close()




def test_owner_post_origin_failure_is_exact_classified_and_never_accepted():
 import json
 a,u,g=setup(owner=True)
 host='owner-m1.example.ts.net:8793'
 prefix={'Host':host,'Content-Type':'application/x-www-form-urlencoded'}
 def post(route,headers):
  c=http.client.HTTPConnection('127.0.0.1',g.server_port,timeout=5)
  try:
   c.request('POST',route,'x=1',{**prefix,**headers})
   r=c.getresponse();payload=r.read()
   return r.status,json.loads(payload) if r.getheader('Content-Type','').startswith('application/json') else None
  finally:c.close()
 try:
  valid='https://'+host
  failures=(
   ({},'ORIGIN_MISSING'),
   ({'Origin':valid,'Sec-Fetch-Site':'cross-site'},'CROSS_SITE'),
   ({'Origin':'http://'+host},'SCHEME_MISMATCH'),
   ({'Origin':'https://bad.example.ts.net:8793'},'HOST_MISMATCH'),
   ({'Origin':'https://owner-m1.example.ts.net:8455'},'PORT_MISMATCH'),
   ({'Origin':'https://owner-m1.example.ts.net:8454'},'SERVE_CONTEXT_UNVERIFIED'),
   ({'Origin':'null'},'SCHEME_MISMATCH'),
  )
  for headers,expected in failures:
   status,payload=post('/settings/routing/optimize',headers)
   assert status==403,(headers,status,payload)
   assert payload=={'error':'owner origin rejected','reason':expected}
  status,payload=post('/release/probe-post',
    {'Origin':valid,'Content-Type':'text/plain'})
  assert (status,payload)==(403,{
      'error':'owner origin rejected','reason':'CONTENT_TYPE_UNSUPPORTED'})
  status,payload=post('/settings/routing/optimize',{'Origin':valid})
  assert status==200 and payload is None
 finally:
  g.shutdown();u.shutdown();g.server_close();u.server_close()


def test_post_rejection_does_not_reveal_origin_details_to_unauthenticated_peer():
 import json
 a,u,g=setup(owner=False)
 try:
  c=http.client.HTTPConnection('127.0.0.1',g.server_port,timeout=5)
  c.request('POST','/settings/routing/optimize','x=1',{'Host':'remote.test'})
  r=c.getresponse();payload=json.loads(r.read())
  assert r.status==403
  assert payload=={'error':'owner verification unavailable'}
 finally:
  g.shutdown();u.shutdown();g.server_close();u.server_close()


def test_remote_health_and_api_fail_closed_when_operator_down():
 a=RemoteAccess(RemoteAccessConfig('S'*48,frozenset({'remote.test'}),False));g=ThreadingHTTPServer(('127.0.0.1',0),handler(a,1));threading.Thread(target=g.serve_forever,daemon=True).start()
 try:
  c=http.client.HTTPConnection('127.0.0.1',g.server_port);c.request('GET','/health',headers={'Host':'remote.test'});assert c.getresponse().status==503
  c.request('GET','/',headers={'Host':'remote.test',});assert c.getresponse().status==503
  c.request('GET','/api/human',headers={'Host':'remote.test',});assert c.getresponse().status==503
 finally:g.shutdown();g.server_close()

def test_remote_rejects_bad_host_and_cross_origin_mutation():
 a,u,g=setup()
 try:
  c=http.client.HTTPConnection('127.0.0.1',g.server_port)
  c.request('GET','/',headers={'Host':'evil.test'});r=c.getresponse();assert r.status==400;r.read()
  c.request('POST','/settings/routing/optimize','function=ALL',
            {'Host':'remote.test','Origin':'http://evil.test',
             'Content-Type':'application/x-www-form-urlencoded'})
  r=c.getresponse();assert r.status==403;r.read()
 finally:g.shutdown();u.shutdown();g.server_close();u.server_close()

def test_remote_operator_csp_allows_only_same_origin_theme_sync_script():
 a,u,g=setup()
 try:
  c=http.client.HTTPConnection('127.0.0.1',g.server_port);c.request('GET','/',headers={'Host':'remote.test'});r=c.getresponse();r.read();csp=r.getheader('Content-Security-Policy');assert "script-src 'unsafe-inline'" in csp and "connect-src 'self'" in csp
 finally:g.shutdown();u.shutdown();g.server_close();u.server_close()

def test_mobile_fetch_metadata_only_rejects_cross_site_mutation():
 a,u,g=setup(owner=True)
 try:
  c=http.client.HTTPConnection('127.0.0.1',g.server_port)
  for site in ('same-site','cross-site','none'):
   h={'Host':'owner-m1.example.ts.net:8793',
      'Origin':'https://owner-m1.example.ts.net:8793','Sec-Fetch-Site':site,
      'Content-Type':'application/x-www-form-urlencoded'}
   c.request('POST','/presentation/theme/toggle','return_to=/',h)
   r=c.getresponse();assert r.status==(403 if site=='cross-site' else 200);r.read()
 finally:g.shutdown();u.shutdown();g.server_close();u.server_close()


def test_responsive_mobile_dashboard_live_read_endpoints_are_proxied():
 a,u,g=setup()
 try:
  for route in (
   '/api/human/status',
   '/api/human/echo/status',
   '/api/human/notices?after=0',
   '/api/provider-services',
   '/api/harness-services',
   '/echo',
  ):
   c=http.client.HTTPConnection('127.0.0.1',g.server_port,timeout=5)
   c.request('GET',route,headers={'Host':'remote.test'})
   r=c.getresponse()
   assert r.status==200,route
   r.read();c.close()
 finally:g.shutdown();u.shutdown();g.server_close();u.server_close()


def test_private_owner_review_get_post_need_whois_and_exact_origin():
 from types import SimpleNamespace
 a=RemoteAccess(RemoteAccessConfig('S'*48,frozenset({'owner-m1.example.ts.net'}),True))
 u=ThreadingHTTPServer(('127.0.0.1',0),U)
 threading.Thread(target=u.serve_forever,daemon=True).start()
 owner=SimpleNamespace(owner_peer=lambda _ip:'same-owner-phone')
 g=ThreadingHTTPServer(('127.0.0.1',0),handler(
  a,u.server_port,mobile_release=object(),tailnet_owner=owner))
 threading.Thread(target=g.serve_forever,daemon=True).start()
 h={'Host':'owner-m1.example.ts.net:8793'}
 def req(method,route,headers=None,body=None):
  c=http.client.HTTPConnection('127.0.0.1',g.server_port,timeout=5)
  c.request(method,route,body=body,headers={**h,**(headers or {})})
  r=c.getresponse();status=r.status;r.read();c.close()
  return status
 try:
  assert req('GET','/development/review')==200
  assert req('GET','/klm/review')==200
  assert req('GET','/development/review',{'Host':'other.invalid'})==400
  assert req('POST','/development/review/preview',
             {'Origin':'https://owner-m1.example.ts.net:8793'},
             'ticket_id=a')==200
  assert req('POST','/klm/review/preview',
             {'Origin':'https://owner-m1.example.ts.net:8793'},
             'review_key=key')==200
  assert req('POST','/development/delegation/enable',
             {'Origin':'https://owner-m1.example.ts.net:8793'},
             'model=m1')==200
  assert req('POST','/development/review/preview',
             {'Origin':'https://attacker.invalid'},'ticket_id=a')==403
  assert req('POST','/development/review/preview',
             {'Origin':'http://owner-m1.example.ts.net:8793'},'ticket_id=a')==403
  assert req('POST','/klm/review/preview',
             {'Origin':'https://owner-m1.example.ts.net:8793',
              'Sec-Fetch-Site':'cross-site'},'review_key=a')==403
  # Refuse all private owner actions even on an otherwise allowed Host when
  # live Tailscale WhoIs does not identify the actual request source.
  owner.owner_peer=lambda _ip:None
  assert req('GET','/development/review')==403
  assert req('POST','/development/review/preview',
             {'Origin':'https://owner-m1.example.ts.net:8793'},
             'ticket_id=a')==403
 finally:g.shutdown();u.shutdown();g.server_close();u.server_close()



def test_every_gateway_write_requires_live_verified_owner_not_just_host():
 a,u,g=setup()
 try:
  c=http.client.HTTPConnection('127.0.0.1',g.server_port)
  for path in ('/action/approve/exact','/action/cancel/exact',
               '/settings/routing/optimize','/presentation/theme/toggle',
               '/notification/dismiss/x'):
   c.request('POST',path,'x=1',
             {'Host':'remote.test','Origin':'http://remote.test',
              'Content-Type':'application/x-www-form-urlencoded'})
   r=c.getresponse();assert r.status==403,path;r.read()
 finally:g.shutdown();u.shutdown();g.server_close()


def test_mobile_release_get_link_metadata_redirect_keeps_exact_sha_and_owner():
 from scripts.remote_gateway import _release_get_query
 assert _release_get_query('')==('',None)
 sha='a'*40
 assert _release_get_query('sha='+sha)==(sha,None)
 assert _release_get_query('utm_source=chatgpt.com')==('', '/release')
 assert _release_get_query('sha='+sha+'&utm_medium=chat&utm_source=chatgpt.com')==(
  sha,'/release?sha='+sha)
 # Unexpected query, multiple SHA and uncontrolled/oversized campaign data
 # remain rejected without reaching a Guard decision or the mobile renderer.
 for q in ('other=x','sha=a&sha=b','utm_source=x&utm_source=y',
           'utm_source='+('a'*129),'utm_source=%0A',
           'utm_source=x&other=y','utm_source=a&'+'x'*600):
  assert _release_get_query(q) is None,q

 class ReleasePage:
  def __init__(self):self.calls=[]
  def render(self,peer,sha):
   self.calls.append((peer,sha))
   return 200,'<html>owner release only</html>'
 page=ReleasePage()
 a,u,g=setup(owner=True,release=page)
 h={'Host':'owner-m1.example.ts.net:8793'}
 def get(route,headers=None):
  conn=http.client.HTTPConnection('127.0.0.1',g.server_port,timeout=5)
  conn.request('GET',route,headers={**h,**(headers or {})})
  r=conn.getresponse();status=r.status;loc=r.getheader('Location');body=r.read()
  conn.close()
  return status,loc,body
 try:
  assert get('/release?utm_source=chatgpt.com')[:2]==(303,'/release')
  assert not page.calls
  assert get('/release?sha='+sha+'&utm_source=chatgpt.com')[:2]==(
   303,'/release?sha='+sha)
  status,loc,body=get('/release?sha='+sha)
  assert status==200 and loc is None and b'owner release only' in body
  assert page.calls==[('verified-owner-node',sha)]
  assert get('/release?utm_source=chatgpt.com',{'Host':'invalid.example'})[0]==400
  assert get('/release?sha='+sha+'&unsupported=value')[0]==400
  assert get('/release?sha='+sha+'&sha='+sha)[0]==400
  assert len(page.calls)==1
 finally:
  g.shutdown();u.shutdown();g.server_close();u.server_close()


def test_verified_serve_port_origin_for_owner_actions(monkeypatch):
 from types import SimpleNamespace
 a=RemoteAccess(RemoteAccessConfig('S'*48,
     frozenset({'owner-m1.example.ts.net'}),True))
 u=ThreadingHTTPServer(('127.0.0.1',0),U)
 threading.Thread(target=u.serve_forever,daemon=True).start()
 peer=SimpleNamespace(
  owner_peer=lambda _ip:None,
  serve_owner_login=lambda login:'serve-owner:42' if login=='owner@example.invalid' else None)
 g=ThreadingHTTPServer(('127.0.0.1',0),handler(
   a,u.server_port,mobile_release=object(),tailnet_owner=peer))
 threading.Thread(target=g.serve_forever,daemon=True).start()
 host='owner-m1.example.ts.net:8793'
 headers={'Host':host,'Tailscale-User-Login':'owner@example.invalid',
          'Origin':'https://owner-m1.example.ts.net:8454',
          'Content-Type':'application/x-www-form-urlencoded'}
 def post(route,extra=None):
  c=http.client.HTTPConnection('127.0.0.1',g.server_port,timeout=5)
  try:
   c.request('POST',route,'x=1',{**headers,**(extra or {})})
   r=c.getresponse();status=r.status;r.read()
   return status
  finally:c.close()
 try:
  assert post('/settings/routing/optimize')==403 # Serve mode not enabled
  monkeypatch.setenv('FOUNDATION_REMOTE_SERVE_OWNER_ENABLED','1')
  for extra in (
   {'Origin':'https://owner-m1.example.ts.net:8455'},
   {'Origin':'https://evil.invalid:8454'},
   {'Origin':'http://owner-m1.example.ts.net:8454'},
   {'Origin':'null'},
   {'Origin':''},
   {'Sec-Fetch-Site':'cross-site'},
   {'Tailscale-User-Login':'other@example.invalid'},
  ):
   assert post('/settings/routing/optimize',extra)==403
  for route in ('/settings/routing/optimize',
                '/development/review/preview',
                '/action/approve/demo'):
   assert post(route)==200,route
  old=g.server_address
  g.server_address=('0.0.0.0',old[1])
  assert post('/action/approve/demo')==403
 finally:
  g.shutdown();u.shutdown();g.server_close();u.server_close()


def test_actual_hmac_owner_probe_with_missing_origin_requires_serve_and_self_referer(monkeypatch):
 """Browser-compat transport test only; not physical Android or Guard proof."""
 import json
 from types import SimpleNamespace
 from urllib.parse import urlencode
 from scripts.m1_mobile_owner_release import MobileOwnerRelease
 host='owner-m1.example.ts.net'
 secret='S'*48
 access=RemoteAccess(RemoteAccessConfig(secret,frozenset({host}),True))
 mobile=MobileOwnerRelease(secret)
 proof=SimpleNamespace(
  owner_peer=lambda _ip: None,
  serve_owner_login=lambda login: 'serve-owner:42' if login=='owner@example.invalid' else None)
 upstream=ThreadingHTTPServer(('127.0.0.1',0),U)
 threading.Thread(target=upstream.serve_forever,daemon=True).start()
 gateway=ThreadingHTTPServer(('127.0.0.1',0),handler(
  access,upstream.server_port,mobile_release=mobile,tailnet_owner=proof))
 threading.Thread(target=gateway.serve_forever,daemon=True).start()
 monkeypatch.setenv('FOUNDATION_REMOTE_SERVE_OWNER_ENABLED','1')
 token=mobile.token('probe-post','serve-owner:42','','')
 body=urlencode({'token':token,'confirmed':'yes'})
 same_origin='https://'+host+':8454'
 base={'Host':host+':8793','Tailscale-User-Login':'owner@example.invalid',
       'Sec-Fetch-Site':'same-origin','Referer':same_origin+'/release',
       'Content-Type':'application/x-www-form-urlencoded'}
 def post(extra,route='/release/probe-post'):
  conn=http.client.HTTPConnection('127.0.0.1',gateway.server_port,timeout=5)
  try:
   conn.request('POST',route,body,headers={**base,**extra})
   result=conn.getresponse()
   return result.status,result.read()
  finally:conn.close()
 try:
  code,page=post({})
  assert code==200 and b'OWNER_POST_TRANSPORT_VERIFIED' in page
  for extra in (
   {'Origin':'null'},
   {'Origin':'https://attacker.invalid'},
   {'Referer':'https://attacker.invalid/release'},
   {'Referer':same_origin+'/settings'},
   {'Referer':same_origin.replace(':8454',':8455')+'/release'},
   {'Referer':'http://'+host+':8454/release'},
   {'Sec-Fetch-Site':'cross-site'},
   {'Sec-Fetch-Site':'same-site'},
   {'Sec-Fetch-Site':'none'},
   {'Sec-Fetch-Site':''},
   {'Tailscale-User-Login':'other@example.invalid'},
  ):
   status,payload=post(extra)
   assert status==403,extra
   assert b'OWNER_POST_TRANSPORT_VERIFIED' not in payload
  status,payload=post({},route='/settings/routing/optimize')
  assert status==403 and b'ORIGIN_MISSING' in payload
  status,payload=post({'Origin':same_origin})
  assert status==200 and b'OWNER_POST_TRANSPORT_VERIFIED' in payload
  monkeypatch.setenv('FOUNDATION_REMOTE_SERVE_OWNER_ENABLED','0')
  status,payload=post({})
  assert status==403 and b'OWNER_POST_TRANSPORT_VERIFIED' not in payload
 finally:
  gateway.shutdown();upstream.shutdown()
  gateway.server_close();upstream.server_close()


def test_release_get_sets_same_origin_referrer_only_after_verified_owner(monkeypatch):
 from types import SimpleNamespace
 host='owner-m1.example.ts.net'
 access=RemoteAccess(RemoteAccessConfig('S'*48,frozenset({host}),True))
 proof=SimpleNamespace(
  owner_peer=lambda _ip: None,
  serve_owner_login=lambda login:'serve-owner:42' if login=='owner@example.invalid' else None)
 release=SimpleNamespace(render=lambda peer,sha:(200,'<html>verified owner</html>'))
 upstream=ThreadingHTTPServer(('127.0.0.1',0),U)
 threading.Thread(target=upstream.serve_forever,daemon=True).start()
 gateway=ThreadingHTTPServer(('127.0.0.1',0),handler(
  access,upstream.server_port,mobile_release=release,tailnet_owner=proof))
 threading.Thread(target=gateway.serve_forever,daemon=True).start()
 monkeypatch.setenv('FOUNDATION_REMOTE_SERVE_OWNER_ENABLED','1')
 def get(path):
  conn=http.client.HTTPConnection('127.0.0.1',gateway.server_port,timeout=5)
  try:
   conn.request('GET',path,headers={'Host':host+':8793',
       'Tailscale-User-Login':'owner@example.invalid'})
   reply=conn.getresponse()
   status,policy=reply.status,reply.getheader('Referrer-Policy')
   reply.read()
   return status,policy
  finally:conn.close()
 try:
  assert get('/release')==(200,'same-origin')
  assert get('/')==(200,'no-referrer')
  assert get('/health')[1]=='no-referrer'
 finally:
  gateway.shutdown();upstream.shutdown()
  gateway.server_close();upstream.server_close()
