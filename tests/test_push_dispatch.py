from ai_foundation.push_dispatch import PushDispatch
class T:
 def __init__(self,fail=False):self.calls=[];self.fail=fail
 def deliver(self,p):
  self.calls.append(p)
  if self.fail:raise RuntimeError('network')
  return {'sent':1}
def payload():return {'notices':[{'level':4,'kind':'work','subject':'j:0','status':'WAITING_HUMAN','summary_ja':'入力が必要です'}]}
def test_dispatch_is_restart_durable_and_deduplicates(tmp_path):
 t=T();p=tmp_path/'seen.json';assert PushDispatch(t,p).dispatch(payload())['sent_notices']==1
 t2=T();assert PushDispatch(t2,p).dispatch(payload())['sent_notices']==0 and not t2.calls
def test_failure_does_not_mark_seen_and_can_retry(tmp_path):
 p=tmp_path/'seen.json';assert PushDispatch(T(True),p).dispatch(payload())['failed_notices']==1
 t=T();assert PushDispatch(t,p).dispatch(payload())['sent_notices']==1
import pytest

def test_corrupt_seen_state_fails_closed_instead_of_replaying_push(tmp_path):
 p=tmp_path/'seen.json';p.write_text('{broken')
 t=T()
 with pytest.raises(RuntimeError,match='state unreadable'):PushDispatch(t,p).dispatch(payload())
 assert not t.calls

def test_failed_delivery_does_not_rewrite_existing_seen_state(tmp_path):
 p=tmp_path/'seen.json';p.write_text('[]');before=p.stat().st_mtime_ns
 PushDispatch(T(True),p).dispatch(payload())
 assert p.stat().st_mtime_ns==before and p.read_text()=='[]'

def test_seen_history_is_bounded_while_new_incidents_still_deliver(tmp_path):
 p=tmp_path/'seen.json';t=T();d=PushDispatch(t,p,max_seen=32)
 for i in range(100):
  x={'notices':[{'level':4,'kind':'work','subject':f'job-{i}','status':'FAILED','summary_ja':'x'}]};assert d.dispatch(x)['sent_notices']==1
 seen=__import__('json').loads(p.read_text());assert len(seen)==32 and len(t.calls)==100
 # Recent duplicate remains suppressed, while an evicted ancient incident may notify again.
 recent={'notices':[{'level':4,'kind':'work','subject':'job-99','status':'FAILED','summary_ja':'x'}]};assert d.dispatch(recent)['sent_notices']==0
