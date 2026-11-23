"""Shared helpers for narrow Foundation presentation gateways."""
import http.client,re
from urllib.parse import parse_qs,urlencode
MAX=2*1024*1024
def current_csrf(upstream):
 c=http.client.HTTPConnection('127.0.0.1',upstream,timeout=5)
 try:
  c.request('GET','/api/gateway/csrf',headers={'Host':f'127.0.0.1:{upstream}'})
  r=c.getresponse();marked=r.getheader('X-Foundation-CSRF-Endpoint','')=='1';data=r.read(8193)
 finally:c.close()
 if r.status==200 and marked:
  import json
  if len(data)>8192:raise RuntimeError('csrf response too large')
  value=json.loads(data).get('csrf')
  if not isinstance(value,str) or not value or len(value)>256:raise RuntimeError('csrf unavailable')
  return value
 if r.status not in (200,404):raise RuntimeError('operator unavailable')
 # Older Operators retain the previous presentation lookup.
 c=http.client.HTTPConnection('127.0.0.1',upstream,timeout=5)
 try:
  c.request('GET','/',headers={'Host':f'127.0.0.1:{upstream}'});r=c.getresponse();data=r.read(MAX)
 finally:c.close()
 if r.status!=200:raise RuntimeError('operator unavailable')
 m=re.search(rb'name=csrf value="([^"]+)',data)
 if not m:raise RuntimeError('csrf unavailable')
 return m.group(1).decode()
def refresh_form_csrf(body,upstream):
 form=parse_qs((body or b'').decode('utf-8'),keep_blank_values=True);form['csrf']=[current_csrf(upstream)]
 return urlencode(form,doseq=True).encode()
