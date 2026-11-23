from pathlib import Path
from ai_foundation.productization import FoundationConfig,backup,restore
from ai_foundation.settings_service import SettingsService
from ai_foundation.provider_onboarding import ProbeResult
from ai_foundation.remote_access import RemoteAccess,RemoteAccessConfig
from ai_foundation.attachment_handoff import AttachmentHandoff,AttachmentRecord
class Secrets:
 def __init__(self):self.d={}
 def save(self,b,s):self.d[b]=s
 def load(self,b):return self.d[b]
 def delete(self,b):return self.d.pop(b,None) is not None
 def available(self,b):return b in self.d
class Probe:
 def probe(self,s,h=None):return ProbeResult(h or 'GROQ','ONLINE',80,'1m',70,'1d')

def test_restored_removed_provider_cannot_regain_execution_without_secret(tmp_path):
 root=tmp_path/'live';root.mkdir();cfg=FoundationConfig(str(root.resolve()));sec=Secrets();svc=SettingsService(root,Probe(),sec);svc.add_provider('gsk_'+'A'*24);binding=svc.registry.bindings()[0]
 backup(cfg,tmp_path/'before-removal');svc.remove_provider(binding);assert not sec.available(binding)
 restored=tmp_path/'restored';restore(tmp_path/'before-removal',restored);old=SettingsService(restored,Probe(),sec)
 assert old.registry.credential(binding) is not None and not old.preflight()['ok']
 assert old.choose_route('CHAT') is None
 assert old.reconcile_missing_credential(binding)['status']=='STALE_REGISTRY_REMOVED' and old.registry.credential(binding) is None

def test_old_session_and_deleted_attachment_grant_do_not_reacquire_authority(tmp_path):
 access=RemoteAccess(RemoteAccessConfig('s'*48,frozenset({'example.test'}),session_seconds=60));token=access.issue_session(now=1000)
 assert access.session_valid(token,now=1059) and not access.session_valid(token,now=1061)
 root=tmp_path/'uploads';root.mkdir();records={('u','a'):AttachmentRecord('a','u',text='secret')};h=AttachmentHandoff(root,lambda a,o:records.get((o,a)))
 grant=h.resolve('u',['a'])[0];assert Path(grant.path).exists();records.clear();h.reconcile_upstream();assert not Path(grant.path).exists()
