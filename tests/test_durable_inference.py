import pytest
from ai_foundation.durable_inference import SQLiteInferenceAttemptStore
from ai_foundation.inference_port import CloudInferencePort,InferenceResultStore
from ai_foundation.core import TaskPlan
class E:
 def __init__(self):self.calls=0
 def invoke(self,b,p):self.calls+=1;return 'ok'
def test_verified_redelivery_reads_durable_result_without_resend(tmp_path):
 s=SQLiteInferenceAttemptStore(tmp_path/'a.db');e=E();p=TaskPlan('r','compute','llm',text='x',effect_id='i')
 CloudInferencePort(e,'b',InferenceResultStore(),'CHAT',s).execute(p)
 out=InferenceResultStore();CloudInferencePort(e,'b',out,'CHAT',s).execute(p)
 assert e.calls==1 and out.get('i')=='ok'
def test_uncertain_dispatch_is_never_blindly_resent(tmp_path):
 s=SQLiteInferenceAttemptStore(tmp_path/'a.db');s.get_or_begin('i','b');e=E()
 with pytest.raises(RuntimeError,match='uncertain'):CloudInferencePort(e,'b',InferenceResultStore(),'CHAT',s).execute(TaskPlan('r','compute','llm',text='x',effect_id='i'))
 assert e.calls==0

def test_definitive_http_failure_allows_durable_rebind(tmp_path):
 from ai_foundation.cloud_execution import ProviderHTTPError
 class Bad:
  def invoke(self,b,p):raise ProviderHTTPError(429)
 s=SQLiteInferenceAttemptStore(tmp_path/'a.db');p=TaskPlan('r','compute','llm',text='x',effect_id='i')
 with pytest.raises(ProviderHTTPError):CloudInferencePort(Bad(),'b1',InferenceResultStore(),'CHAT',s).execute(p)
 assert s.get('i').status=='FAILED'
 good=E();out=InferenceResultStore();CloudInferencePort(good,'b2',out,'CHAT',s).execute(p)
 assert good.calls==1 and out.get('i')=='ok' and s.get('i').binding=='b2' and s.get('i').status=='VERIFIED'

def test_transport_failure_stays_uncertain_and_blocks_rebind(tmp_path):
 class Lost:
  def invoke(self,b,p):raise TimeoutError('lost after dispatch')
 s=SQLiteInferenceAttemptStore(tmp_path/'a.db');p=TaskPlan('r','compute','llm',text='x',effect_id='i')
 with pytest.raises(TimeoutError):CloudInferencePort(Lost(),'b1',InferenceResultStore(),'CHAT',s).execute(p)
 assert s.get('i').status=='UNCERTAIN'
 with pytest.raises(ValueError,match='binding changed'):CloudInferencePort(E(),'b2',InferenceResultStore(),'CHAT',s).execute(p)

def test_verified_durable_result_is_reused_without_rebinding_dispatch(tmp_path):
 s=SQLiteInferenceAttemptStore(tmp_path/'a.db');s.get_or_begin('i','b1');s.complete('i','ok')
 prior=s.get_or_begin('i','b2')
 assert prior.status=='VERIFIED' and prior.binding=='b1' and prior.result=='ok'
