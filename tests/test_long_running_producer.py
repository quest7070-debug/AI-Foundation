import pytest
from ai_foundation.long_running_producer import LongRunningProducer
from ai_foundation.capability_request import CapabilityRequest
class A:
 def __init__(self):self.rows={};self.events=[]
 def put(self,j,r):self.events.append(('put',j));self.rows[j]=r
 def forget(self,j):self.events.append(('forget',j));self.rows.pop(j,None)
class W:
 def __init__(self,fail=False):self.fail=fail;self.events=[]
 def submit(self,s):self.events.append(('submit',s.job_id));
 def status(self,j):return 'SUBMITTED'
class Good(W):
 def submit(self,s):self.events.append(('submit',s.job_id));return s.job_id
class Bad(W):
 def submit(self,s):self.events.append(('submit',s.job_id));raise RuntimeError('down')

def req():return CapabilityRequest('DATA',owner_id='u',data_operation='json_summary',long_running=True)
def test_authority_is_persisted_before_runtime_submission():
 a=A();w=Good();p=LongRunningProducer(a,w);assert p.submit('j',req(),'[]')=='j';assert 'j' in a.rows and a.events==[('put','j')] and w.events==[('submit','j')]
def test_ambiguous_runtime_submission_retains_staged_authority_for_safe_replay():
 a=A();w=Bad();p=LongRunningProducer(a,w)
 with pytest.raises(RuntimeError):p.submit('j',req(),'[]')
 assert 'j' in a.rows and a.events==[('put','j')]
def test_invalid_submission_never_stages_authority():
 a=A();w=Good();p=LongRunningProducer(a,w)
 with pytest.raises(ValueError):p.submit('j',CapabilityRequest('DATA',owner_id='u',data_operation='json_summary'),'[]')
 assert not a.rows and not w.events
