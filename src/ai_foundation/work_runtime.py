from dataclasses import dataclass
from .durable_work import DurableWorkRunner
from .orchestration import WorkStatus
@dataclass
class DurableWorkRuntimeCall:
 runner: DurableWorkRunner
 def run(self,job_id,steps,reconcilers=None):
  reconcilers=reconcilers or {}
  saved=self.runner.store.load(job_id)
  for step in saved:
   if step.status is WorkStatus.RUNNING:
    reconcile=reconcilers.get(step.name)
    if reconcile is None: raise RuntimeError('orphaned RUNNING step requires reconciliation')
    status=self.runner.reconcile_running(job_id,step.position,reconcile)
    if status is not WorkStatus.VERIFIED: raise RuntimeError('work reconciliation incomplete')
  status=self.runner.execute(job_id,steps)
  if status is WorkStatus.VERIFIED: return 'VERIFIED_COMPLETE'
  if status is WorkStatus.WAITING_HUMAN: return 'WAITING_HUMAN'
  raise RuntimeError(f'work not terminal: {status.value}')
