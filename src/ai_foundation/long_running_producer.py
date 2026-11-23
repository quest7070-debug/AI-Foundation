"""Fail-closed producer transaction for explicit long-running work."""
from __future__ import annotations
from .long_running import LongRunningSubmission

class LongRunningProducer:
 def __init__(self,authority_store,work_service):self.authority_store=authority_store;self.work_service=work_service
 def submit(self,job_id,request,text):
  submission=LongRunningSubmission(job_id,request,text)
  # Authority must exist before Hatchet can dispatch the job. Once the trigger is
  # attempted its outcome can be ambiguous (remote run created, response lost), so
  # authority must remain durable for worker rehydration and idempotent replay.
  # Invalid submissions fail before this point; terminal cleanup is an explicit
  # lifecycle operation, never inferred from a transport exception.
  self.authority_store.put(job_id,request)
  return self.work_service.submit(submission)
 def status(self,job_id):return self.work_service.status(job_id)
