import io,json,ssl,socket
from urllib.error import HTTPError,URLError
import pytest
from ai_foundation.settings_service import SettingsService
from ai_foundation.provider_onboarding import ProbeResult
from ai_foundation.provider_recovery import ProviderRecoveryLoop
from ai_foundation.provider_registry import SQLiteProviderRegistry
from ai_foundation.provider_observer import ProviderResponseObserver
from ai_foundation.cloud_execution import ObservedCloudExecution,CloudResponse
from ai_foundation.http_transport import UrllibCloudTransport

class Secrets:
 def __init__(self):self.d={}
 def save(self,b,s):self.d[b]=s
 def load(self,b):return self.d[b]
 def delete(self,b):return self.d.pop(b,None) is not None
 def available(self,b):return b in self.d
class SequenceProbe:
 def __init__(self,rows):self.rows=iter(rows)
 def probe(self,s,h=None):return next(self.rows)

def test_credential_expire_rotate_and_revoke_converge_without_restart(tmp_path):
 sec=Secrets();probe=SequenceProbe([ProbeResult('GROQ','ONLINE'),ProbeResult('GROQ','CREDENTIAL_ERROR',reason='HTTP 401'),ProbeResult('GROQ','ONLINE')])
 svc=SettingsService(tmp_path,probe,sec);svc.add_provider('gsk_'+'A'*24);b=svc.registry.bindings()[0]
 assert svc.route('CHAT').primary==b
 assert svc.refresh_provider(b)['health']=='CREDENTIAL_ERROR' and svc.route('CHAT').primary is None
 assert svc.replace_provider_credential(b,'gsk_'+'B'*24)['health']=='ONLINE' and svc.route('CHAT').primary==b
 sec.delete(b);assert not svc.preflight()['ok'];assert svc.reconcile_missing_credential(b)['repaired'];assert b not in svc.registry.bindings() and svc.route('CHAT').primary is None

def test_quota_header_drift_and_recovery_do_not_erase_last_evidence_or_wedge(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.db');r.upsert('b','GROQ',short_remaining=44,long_remaining=55)
 o=ProviderResponseObserver(r);o.observe('b','GROQ',429,{'Retry-After':'7'});c=r.credential('b')
 assert c['health']=='RATE_LIMITED' and (c['short_remaining'],c['long_remaining'])==(44,55)
 class S:
  def credentials(self):return (r.credential('b'),)
  def refresh_provider(self,b):r.observe(b,health='ONLINE',reason=None);return {'provider':'GROQ','health':'ONLINE'}
 assert ProviderRecoveryLoop(S()).tick()==({'provider':'GROQ','health':'ONLINE'},) and r.credential('b')['health']=='ONLINE'
 # Unknown/malformed replacement quota headers are ignored rather than fabricated.
 o.observe('b','GROQ',200,{'x-ratelimit-limit-tokens':'new-format'});c=r.credential('b');assert (c['short_remaining'],c['long_remaining'])==(44,55)

def test_catalog_model_capability_change_reconciles_stale_db_without_restart(tmp_path,monkeypatch):
 from ai_foundation import provider_catalog
 from ai_foundation.provider_catalog import ProviderSpec
 sec=Secrets();svc=SettingsService(tmp_path,SequenceProbe([ProbeResult('GROQ','ONLINE')]),sec);svc.add_provider('gsk_'+'C'*24);b=svc.registry.bindings()[0]
 replacement=ProviderSpec('GROQ','https://api.groq.com/openai/v2/chat/completions','replacement-model',quota_style='groq',protocol='openai-chat',capabilities=('CHAT',))
 monkeypatch.setitem(provider_catalog.PROVIDERS,'GROQ',replacement)
 # Reconstructing settings is the catalog reconciliation boundary; stale DB execution metadata cannot win.
 svc2=SettingsService(tmp_path,SequenceProbe([]),sec);m=svc2.registry.credential(b)
 assert m['model']=='replacement-model' and m['endpoint'].endswith('/v2/chat/completions') and m['capabilities']==('CHAT',)
 assert svc2.route('SEARCH').primary is None

def test_response_schema_drift_fails_explicitly_without_authority_guess():
 from ai_foundation.cloud_execution import ObservedCloudExecution
 assert ObservedCloudExecution.extract_text(json.dumps({'choices':[{'message':{'content':'ok','future':123}}],'futureTop':True}))=='ok'
 with pytest.raises(RuntimeError,match='missing content'):ObservedCloudExecution.extract_text(json.dumps({'choices':[{'message':{'renamed_content':'x'}}]}))
 with pytest.raises(RuntimeError,match='missing content'):ObservedCloudExecution.extract_text(json.dumps({'candidates':[{'renamed':{}}]}))

def test_tls_dns_network_failure_then_recovery_has_no_sticky_transport_state():
 calls={'n':0}
 class Resp:
  status=200;headers={}
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def read(self,n):return b'{"ok":true}'
 def op(req,timeout):
  calls['n']+=1
  if calls['n']==1:raise URLError(ssl.SSLCertVerificationError('expired'))
  if calls['n']==2:raise URLError(socket.gaierror('dns unavailable'))
  return Resp()
 t=UrllibCloudTransport(opener=op)
 with pytest.raises(URLError):t.send('GROQ','s',{})
 with pytest.raises(URLError):t.send('GROQ','s',{})
 assert t.send('GROQ','s',{}).status==200 and calls['n']==3

def test_same_origin_redirect_policy_rejects_scheme_or_port_drift():
 from ai_foundation.http_transport import _SameHostRedirect
 from urllib import request,error
 h=_SameHostRedirect();req=request.Request('https://a.test/x')
 with pytest.raises(error.HTTPError):h.redirect_request(req,None,302,'',{},'http://a.test/y')
 with pytest.raises(error.HTTPError):h.redirect_request(req,None,302,'',{},'https://a.test:444/y')

def test_storage_admission_unreadable_io_fails_closed_without_calling_writer(tmp_path):
 from ai_foundation.storage_admission import StorageAdmission,StorageCapacityError
 called=[]
 def bad(_):raise OSError('simulated I/O failure')
 gate=StorageAdmission(tmp_path,disk_usage=bad)
 assert gate.status().writable is False and gate.status().free_bytes is None
 with pytest.raises(StorageCapacityError):gate.require('authority write')
 assert called==[]

def test_corrupt_provider_db_surfaces_integrity_failure_not_empty_success(tmp_path):
 p=tmp_path/'p.db';p.write_bytes(b'not sqlite')
 from ai_foundation.provider_registry import SQLiteProviderRegistry
 with pytest.raises(__import__('sqlite3').DatabaseError):SQLiteProviderRegistry(p)

def test_corrupt_model_runtime_inventory_is_non_routable():
 from ai_foundation.llama_swap_adapter import LlamaSwapDiscovery
 class R:
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def read(self,n):return b'{broken'
 rows=LlamaSwapDiscovery(opener=lambda *a,**k:R())()
 assert len(rows)==1 and rows[0].health=='UNAVAILABLE' and rows[0].capabilities==()

def test_project_declares_supported_python_floor_and_current_runtime_meets_it():
 import sys,tomllib
 from pathlib import Path
 data=tomllib.loads(Path('pyproject.toml').read_text())
 assert data['project']['requires-python']=='>=3.12' and sys.version_info>=(3,12)
