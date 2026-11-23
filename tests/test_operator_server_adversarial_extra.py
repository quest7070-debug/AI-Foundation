import http.client,threading
from types import SimpleNamespace
from ai_foundation.operator_server import OperatorApplication,serve
class A: pass
class Settings:
 def add_provider(self,*a): raise ValueError('secret='+a[0])
def setup():
 c=SimpleNamespace(data_dir='/tmp',work_db='none.sqlite',guard_db='none.sqlite',trace_file='none',toolhive_server='x',toolhive_mount='x');app=OperatorApplication(c,A(),csrf_token='tok',settings=Settings());sv=serve(app);threading.Thread(target=sv.serve_forever,daemon=True).start();return sv
def post(sv,body,headers=None):
 c=http.client.HTTPConnection('127.0.0.1',sv.server_port);h={'Content-Type':'application/x-www-form-urlencoded','Content-Length':str(len(body))};h.update(headers or {});c.request('POST','/settings/provider/add',body,h);r=c.getresponse();return r.status,r.read().decode()
def test_header_csrf_still_reads_body():
 s=setup();status,_=post(s,'api_key=dummy&tier=FREE',{'X-Foundation-CSRF':'tok'});s.shutdown();assert status==400
def test_bad_host_rejected():
 s=setup();status,_=post(s,'csrf=tok&api_key=x',{'Host':'evil.example'});s.shutdown();assert status==403
def test_oversize_rejected_before_parse():
 s=setup();status,_=post(s,'x'*8193);s.shutdown();assert status==413
def test_provider_error_never_reflects_key():
 s=setup();status,b=post(s,'csrf=tok&api_key=SUPERSECRET&tier=FREE');s.shutdown();assert status==400 and 'SUPERSECRET' not in b
def test_invalid_tier_sanitized():
 s=setup();status,b=post(s,'csrf=tok&api_key=x&tier=ROOT');s.shutdown();assert status==400 and 'ROOT' not in b
