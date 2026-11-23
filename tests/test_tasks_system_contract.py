from ai_foundation.human_operations import tasks
from ai_foundation.human_view import from_snapshot
from ai_foundation.human_renderer import render
from ai_foundation.task_intake import TaskIntake
from ai_foundation.orchestration import WorkStatus

class Snap:
 def __init__(self,ready=True,checks=(),services=(),work=None,attention=()):
  self.d={'ready':ready,'waiting_human':0,'effects':{},'work':work or {},'attention':attention,'checks':checks,'services':services,'backup':None,'update':None,'trace_present':False}
 def as_dict(self):return self.d

def test_tasks_contract_running_and_failed_only_with_result_evidence(tmp_path):
 i=TaskIntake(tmp_path/'w.db'); planned=i.submit('queued'); running=i.submit('working'); waiting=i.submit('waiting for human'); failed=i.submit('broken'); done=i.submit('done')
 i.store.set(running.job_id,0,WorkStatus.RUNNING,'')
 i.store.set(waiting.job_id,0,WorkStatus.WAITING_HUMAN,'decision')
 i.store.set(failed.job_id,0,WorkStatus.FAILED,'failure detail')
 i.store.set(done.job_id,0,WorkStatus.VERIFIED,'completed')
 rows=tasks(i)
 assert {(x.text,x.status) for x in rows}=={('working','RUNNING'),('waiting for human','WAITING_HUMAN'),('broken','FAILED')}
 page=render(from_snapshot(Snap(work={'RUNNING':1}),tasks=rows),'responsive')
 assert 'working' in page and 'waiting for human' in page and 'broken' in page and 'queued' not in page and 'done' not in page
 assert 'SUBMIT TASK' not in page and 'RUN TASK' not in page

def test_system_contract_ready_and_attention_are_truthful():
 ready=render(from_snapshot(Snap(True,checks=({'name':'db','ok':True,'detail':'ok'},),services=({'name':'LOCAL COMPUTE','ok':True,'detail':'ready'},))),'responsive')
 assert 'SYSTEM READY' in ready and 'ALL CORE CHECKS PASSED' in ready and 'SYSTEM ATTENTION' not in ready
 bad=render(from_snapshot(Snap(False,checks=({'name':'db','ok':False,'detail':'bad'},),services=({'name':'LOCAL COMPUTE','ok':False,'detail':'down'},))),'responsive')
 assert 'SYSTEM ATTENTION' in bad and 'CHECKS FAILED / 1' in bad and 'SERVICES DOWN / 1' in bad
 assert 'db FAILED' in bad and 'LOCAL COMPUTE DOWN' in bad

def test_waiting_task_and_notification_share_job_then_approval_resumes_same_job(tmp_path):
 from ai_foundation.operator_server import OperatorApplication
 from ai_foundation.human_operations import tasks
 class Config:
  data_dir=str(tmp_path); work_db='work.db'
 class Result:
  ok=True; status='APPROVED'
 class Actions:
  def approve_run(self,subject):
   assert subject==receipt.job_id
   return Result()
 class Done:
  status='VERIFIED_COMPLETE'; result='continued'; route_kind='LOCAL'; route_binding='local:test'
 app=OperatorApplication(Config(),Actions(),inference=lambda receipt:Done())
 receipt=app.intake.submit('needs approval')
 app.intake.store.set(receipt.job_id,0,WorkStatus.WAITING_HUMAN,'WAITING_HUMAN')
 before=tasks(app.intake)
 assert [(x.job_id,x.status) for x in before]==[(receipt.job_id,'WAITING_HUMAN')]
 result=app.act('approve',receipt.job_id)
 assert result.ok
 assert app.intake.store.load(receipt.job_id)[0].status is WorkStatus.VERIFIED
 # Same durable job was resumed and completed; no replacement/restarted intake row was created.
 assert len(app.intake.recent())==1 and app.intake.recent()[0].job_id==receipt.job_id
 assert tasks(app.intake)==()
