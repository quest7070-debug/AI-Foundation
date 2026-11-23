from ai_foundation.task_intake import TaskIntake
from ai_foundation.human_operations import tasks
class O:
 status='VERIFIED_COMPLETE';result='answer from compute'
def test_completed_intake_is_not_exposed_as_active_human_task(tmp_path):
 x=TaskIntake(tmp_path/'w.db');r=x.submit('hello');assert x.execute(r.job_id,lambda receipt:O())=='answer from compute'
 assert tasks(x)==()
