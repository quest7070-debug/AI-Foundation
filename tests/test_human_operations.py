from ai_foundation.human_operations import notices,tasks
from ai_foundation.task_intake import TaskIntake
class Snap:
 def as_dict(self):return {'attention':[{'kind':'approval','id':'run1','run_id':'run1','status':'WAITING_HUMAN','action':'production_deploy','approval_ref':'a'*64},{'kind':'effect','id':'e1','status':'UNCERTAIN'}]}
def test_notices_priority_and_authority():
 n=notices(Snap());assert n[0].level==5 and n[0].status=='UNCERTAIN';assert n[1].level==4 and n[1].actionable and 'AUTHORIZE' in n[1].detail_ja
def test_tasks_show_only_running_and_failed_work(tmp_path):
 i=TaskIntake(tmp_path/'w.sqlite');planned=i.submit('planned');running=i.submit('running');waiting=i.submit('waiting');failed=i.submit('failed')
 from ai_foundation.orchestration import WorkStatus
 i.store.set(running.job_id,0,WorkStatus.RUNNING,'');i.store.set(waiting.job_id,0,WorkStatus.WAITING_HUMAN,'approval/input');i.store.set(failed.job_id,0,WorkStatus.FAILED,'boom')
 rows={x.job_id:x for x in tasks(i)}
 assert {k:x.status for k,x in rows.items()}=={running.job_id:'RUNNING',waiting.job_id:'WAITING_HUMAN',failed.job_id:'FAILED'}
 assert {x.verification for x in rows.values()}=={'UNVERIFIED'}
 assert rows[failed.job_id].result=='boom'
 # A verified earlier step and a current running step without a receipt
 # must not make the unresolved job look completed or reuse stale evidence.
 from ai_foundation.task_result import TaskResult
 i.store.ensure(running.job_id,['intake','next'])
 i.store.set(running.job_id,0,WorkStatus.VERIFIED,TaskResult('old result','VERIFIED',evidence=('old-evidence',)).encode())
 i.store.set(running.job_id,1,WorkStatus.RUNNING,'')
 row=next(x for x in tasks(i) if x.job_id==running.job_id)
 assert row.status=='RUNNING' and row.verification=='UNVERIFIED'
 assert row.result=='' and row.evidence==()

def test_failed_is_attention_not_critical_and_uncertain_uses_effect_id():
 class S:
  def as_dict(self):return {'attention':[{'kind':'effect','id':'effect-7','run_id':'run-7','status':'UNCERTAIN'},{'kind':'work','id':'job-1','run_id':'run-x','status':'FAILED'}]}
 rows=notices(S());u=next(x for x in rows if x.status=='UNCERTAIN');f=next(x for x in rows if x.status=='FAILED');assert u.level==5 and u.subject=='effect-7';assert f.level==3

def test_notices_same_level_newest_first():
 class S:
  def as_dict(self):return {'attention':[{'kind':'work','id':'old','run_id':'old','status':'FAILED','updated_at':10},{'kind':'work','id':'new','run_id':'new','status':'FAILED','updated_at':20}]}
 assert [n.subject for n in notices(S())]==['new','old']

def test_waiting_work_is_input_not_authority_approval():
 class Snap:
  def as_dict(self): return {'attention':[{'kind':'work','id':'job:0','job_id':'job','status':'WAITING_HUMAN','updated_at':1}]}
 n=notices(Snap())[0]
 assert n.input_required and not n.actionable
 assert '権限承認ではありません' in n.detail_ja

def test_notification_runtime_semantics_use_five_level_scale():
 class S:
  def as_dict(self):return {'attention':[{'kind':'work','id':'f','run_id':'f','status':'FAILED'},{'kind':'work','id':'w','run_id':'w','status':'WAITING_HUMAN'},{'kind':'effect','id':'u','status':'UNCERTAIN'}]}
 rows=notices(S());assert [(x.status,x.level) for x in rows]==[('UNCERTAIN',5),('WAITING_HUMAN',4),('FAILED',3)]


def test_notification_level_outside_five_level_scale_is_rejected():
 import pytest
 from ai_foundation.human_operations import HumanNotice
 with pytest.raises(ValueError,match='1..5'):HumanNotice(6,'x','x','FAILED','x','x')

def test_resolved_tasks_are_purged_but_failed_errors_remain_visible(tmp_path):
 i=TaskIntake(tmp_path/'w.sqlite');done=i.submit('done');failed=i.submit('failed')
 from ai_foundation.orchestration import WorkStatus
 i.store.set(done.job_id,0,WorkStatus.VERIFIED,'ok');i.store.set(failed.job_id,0,WorkStatus.FAILED,'boom')
 assert i.purge_terminal()==1
 assert [x.job_id for x in i.recent()]==[failed.job_id]
 assert i.store.load(done.job_id)==[] and i.store.load(failed.job_id)[0].status is WorkStatus.FAILED

def test_code_scope_and_technical_review_use_original_notifications():
 class S:
  def as_dict(self):
   return {'attention':[
    {'kind':'work','id':'mcp-development-request:owner:ticket:0','step':'development-request','status':'WAITING_HUMAN'},
    {'kind':'approval','id':'development-scope-ordinary-v1','run_id':'development-scope-ordinary-v1','action':'development_scope','target':'ordinary-code-scope:'+'b'*64,'approval_ref':'c'*64,'status':'WAITING_HUMAN'},
    {'kind':'approval','id':'old','run_id':'old','action':'production_deploy','approval_ref':'','status':'WAITING_HUMAN'}]}
 rows={n.subject:n for n in notices(S())}
 scope=rows['development-scope-ordinary-v1']
 assert scope.actionable and not scope.input_required
 assert '本番反映は対象外' in scope.detail_ja and 'Strata優先' in scope.detail_ja
 work=rows['mcp-development-request:owner:ticket:0']
 assert work.level==3 and not work.input_required and not work.actionable
 assert not rows['old'].actionable
