from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.human_input import HumanInputService
from ai_foundation.orchestration import WorkStatus

def waiting(tmp_path):
 s=SQLiteWorkStore(tmp_path/'w.db'); s.ensure('job',['step']); s.set('job',0,WorkStatus.WAITING_HUMAN,'need region'); return s

def test_response_is_durable_and_scoped_to_exact_waiting_step(tmp_path):
 s=waiting(tmp_path); s.ensure('other',['step']); s.set('other',0,WorkStatus.WAITING_HUMAN,'need x')
 seen=[]
 svc=HumanInputService(s,lambda job,pos: seen.append((job,pos,s.pending_human_input(job,pos))) or WorkStatus.VERIFIED)
 r=svc.respond('job:0','  ap-northeast-1  ')
 assert r.ok and r.status=='VERIFIED'
 assert seen==[('job',0,'ap-northeast-1')]
 assert s.load('other')[0].status is WorkStatus.WAITING_HUMAN

def test_response_rejected_unless_exact_step_is_waiting(tmp_path):
 s=SQLiteWorkStore(tmp_path/'w.db');s.ensure('job',['step'])
 assert HumanInputService(s).respond('job:0','x').status=='NOT_WAITING'
 assert HumanInputService(s).respond('missing:0','x').status=='NOT_FOUND'

def test_response_survives_restart_before_resume(tmp_path):
 s=waiting(tmp_path); HumanInputService(s).respond('job:0','human answer')
 reopened=SQLiteWorkStore(tmp_path/'w.db')
 assert reopened.pending_human_input('job',0)=='human answer'


def test_resume_failure_then_restart_reuses_durable_input_once(tmp_path):
 from ai_foundation.task_intake import TaskIntake
 class Waiting: status='WAITING_HUMAN'; result=None
 class Done: status='VERIFIED_COMPLETE'; result='finished with human answer'; route_kind='LOCAL'; route_binding='local-general'
 intake=TaskIntake(tmp_path/'flow.db'); receipt=intake.submit('needs input')
 assert intake.execute(receipt.job_id,lambda _:Waiting())=='WAITING_HUMAN'
 first=HumanInputService(intake.store,lambda *_: (_ for _ in ()).throw(RuntimeError('process lost during resume')))
 r=first.respond(receipt.job_id+':0','human answer')
 assert r.ok and r.status=='INPUT_RECORDED_RESUME_FAILED'
 assert intake.store.pending_human_input(receipt.job_id,0)=='human answer'
 # Reconstruct services from the durable DB, as after process restart.
 reopened=TaskIntake(tmp_path/'flow.db'); calls=[]
 def resume(job,pos):
  answer=reopened.store.pending_human_input(job,pos); calls.append(answer)
  result=reopened.execute(job,lambda rec:Done())
  if result!='WAITING_HUMAN': reopened.store.consume_human_input(job,pos)
  return result
 second=HumanInputService(reopened.store,resume)
 r2=second.respond(receipt.job_id+':0','human answer 2')
 assert not r2.ok and r2.status=='INPUT_ALREADY_RECORDED'
 assert calls==[]
 assert reopened.store.pending_human_input(receipt.job_id,0)=='human answer'
 # Recovery resumes the already committed answer; it does not require a second answer.
 r3=HumanInputService(reopened.store,resume).respond(receipt.job_id+':0','human answer')
 assert r3.ok and r3.status=='finished with human answer'
 assert calls==['human answer']
 assert reopened.store.load(receipt.job_id)[0].status is WorkStatus.VERIFIED


def test_committed_answer_rejected_after_waiting_context_changes(tmp_path):
 s=waiting(tmp_path); svc=HumanInputService(s); assert svc.respond('job:0','answer').ok
 # Same job/step but a newly issued question/context must not consume the old answer.
 s.set('job',0,WorkStatus.WAITING_HUMAN,'different question')
 r=HumanInputService(s).respond('job:0','answer')
 assert not r.ok and r.status=='CONTEXT_CHANGED'
 assert s.pending_human_input('job',0)=='answer'


def test_exact_waiting_job_resume_is_single_claim_under_duplicate_human_submit(tmp_path):
 from ai_foundation.task_intake import TaskIntake
 class Waiting: status='WAITING_HUMAN'; result=None
 class Done: status='VERIFIED_COMPLETE'; result='done'; route_kind='LOCAL'; route_binding='local-general'
 intake=TaskIntake(tmp_path/'single.db'); receipt=intake.submit('needs input')
 assert intake.execute(receipt.job_id,lambda _:Waiting())=='WAITING_HUMAN'
 calls=[]
 def resume(job,pos):
  calls.append((job,pos,intake.store.pending_human_input(job,pos)))
  result=intake.execute(job,lambda _:Done())
  if result!='WAITING_HUMAN': intake.store.consume_human_input(job,pos)
  return result
 svc=HumanInputService(intake.store,resume)
 first=svc.respond(receipt.job_id+':0','answer')
 second=svc.respond(receipt.job_id+':0','answer')
 assert first.ok and first.status=='done'
 assert not second.ok and second.status=='NOT_WAITING'
 assert calls==[(receipt.job_id,0,'answer')]
 assert intake.store.load(receipt.job_id)[0].status is WorkStatus.VERIFIED
 assert intake.store.pending_human_input(receipt.job_id,0) is None
