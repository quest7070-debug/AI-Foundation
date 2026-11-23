import pytest
from ai_foundation.long_running_authority import LongRunningAuthorityStore,DurableLongRunningExecutor
from ai_foundation.capability_request import CapabilityRequest,AttachmentGrant

def test_authority_survives_restart_and_runtime_identity_cannot_expand_it(tmp_path):
 p=tmp_path/'authority.sqlite';s=LongRunningAuthorityStore(p)
 req=CapabilityRequest('CODE',owner_id='u',repo_root='/trusted/repo',long_running=True)
 s.put('j',req); rebuilt=LongRunningAuthorityStore(p)
 got=rebuilt.get('j','u','CODE');assert got.repo_root=='/trusted/repo' and got.long_running
 with pytest.raises(PermissionError):rebuilt.get('j','other','CODE')
 with pytest.raises(PermissionError):rebuilt.get('j','u','DATA')

def test_authority_rejects_chat_and_resolved_attachment_paths(tmp_path):
 s=LongRunningAuthorityStore(tmp_path/'a.sqlite')
 with pytest.raises(ValueError):s.put('j',CapabilityRequest('CHAT',owner_id='u',long_running=True))
 a=AttachmentGrant('a','u','/tmp/private')
 with pytest.raises(PermissionError):s.put('j2',CapabilityRequest('SEARCH',owner_id='u',attachments=(a,),long_running=True))

def test_executor_rehydrates_host_authority_not_worker_payload(tmp_path):
 s=LongRunningAuthorityStore(tmp_path/'a.sqlite');s.put('j',CapabilityRequest('DATA',owner_id='u',data_operation='json_summary',long_running=True))
 class X:
  def __init__(self):self.calls=[]
  def execute(self,r,t,j):self.calls.append((r,t,j));return 'ok'
 x=X();e=DurableLongRunningExecutor(s,x)
 assert e.execute_long_running('j','DATA','u','[1,2]')=={'status':'VERIFIED_COMPLETE','result':'ok'}
 assert x.calls[0][0].data_operation=='json_summary'
 s.forget('j')
 with pytest.raises(KeyError):e.execute_long_running('j','DATA','u','x')


def test_exact_authority_replay_is_idempotent_but_changed_replay_fails_closed(tmp_path):
 s=LongRunningAuthorityStore(tmp_path/'a.sqlite');r=CapabilityRequest('DATA',owner_id='u',data_operation='json_summary',long_running=True)
 s.put('stable',r);s.put('stable',r)
 assert s.get('stable','u','DATA')==r
 with pytest.raises(PermissionError,match='replay mismatch'):
  s.put('stable',CapabilityRequest('DATA',owner_id='other',data_operation='json_summary',long_running=True))
 with pytest.raises(PermissionError,match='replay mismatch'):
  s.put('stable',CapabilityRequest('SEARCH',owner_id='u',long_running=True))
