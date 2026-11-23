import pytest
from ai_foundation.long_running import LongRunningSubmission,LongRunningWorkService
from ai_foundation.capability_request import CapabilityRequest
class P:
 def __init__(self):self.rows={}
 def submit(self,s):self.rows[s.job_id]='SUBMITTED';return s.job_id
 def status(self,j):return self.rows.get(j,'UNKNOWN')

def test_explicit_long_running_submission_survives_caller_boundary():
 p=P();s=LongRunningSubmission('j1',CapabilityRequest('SEARCH',long_running=True),'research')
 svc=LongRunningWorkService(p);assert svc.submit(s)=='j1' and svc.status('j1')=='SUBMITTED'

def test_normal_chat_and_untrusted_long_running_are_not_submitted():
 with pytest.raises(ValueError):LongRunningSubmission('j',CapabilityRequest('SEARCH'),'x')
 with pytest.raises(PermissionError):LongRunningSubmission('j',CapabilityRequest('CHAT',long_running=True),'x')
