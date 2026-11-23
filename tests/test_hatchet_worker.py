import pytest
from ai_foundation.hatchet_worker import LongRunningWorkItem,LongRunningWorkerHandler,build_worker

def test_worker_input_is_minimal_and_rejects_authority_fields():
 x=LongRunningWorkItem.parse({'job_id':'j','capability':'CODE','owner_id':'u','text':'inspect'})
 assert x.capability=='CODE'
 for field in ('repo_root','file_read_root','pc_target','credential_binding'):
  with pytest.raises(ValueError):LongRunningWorkItem.parse({'job_id':'j','capability':'CODE','owner_id':'u','text':'inspect',field:'/authority'})

def test_worker_rejects_chat_and_missing_identity():
 with pytest.raises(PermissionError):LongRunningWorkItem.parse({'job_id':'j','capability':'CHAT','owner_id':'u','text':'x'})
 with pytest.raises(ValueError):LongRunningWorkItem.parse({'job_id':'','capability':'SEARCH','owner_id':'u','text':'x'})

class E:
 def __init__(self):self.calls=[]
 def execute_long_running(self,*args):self.calls.append(args);return {'status':'VERIFIED'}
def test_handler_delegates_only_parsed_identity_to_foundation_executor():
 e=E();h=LongRunningWorkerHandler(e)
 assert h({'job_id':'j','capability':'DATA','owner_id':'u','text':'sum'})=={'status':'VERIFIED'}
 assert e.calls==[('j','DATA','u','sum')]

class Workflow:
 def __init__(self):self.fn=None
 def task(self,**kw):
  assert kw['retries']==0
  def deco(fn):self.fn=fn;return fn
  return deco
class H:
 def __init__(self):self.wf=Workflow();self.args=None
 def workflow(self,**kw):assert kw['name']=='wf';return self.wf
 def worker(self,name,workflows):self.args=(name,workflows);return 'worker'
def test_build_worker_registers_one_zero_retry_workflow():
 h=H();e=E();w=build_worker(h,LongRunningWorkerHandler(e),worker_name='worker',workflow_name='wf')
 assert w=='worker' and h.args==('worker',[h.wf])
 assert h.wf.fn({'job_id':'j','capability':'SEARCH','owner_id':'u','text':'q'},None)=={'status':'VERIFIED'}
