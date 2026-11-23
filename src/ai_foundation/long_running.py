"""Explicit durable submission boundary for owner-approved long-running Foundation work."""
from __future__ import annotations
from dataclasses import dataclass
from .capability_request import CapabilityRequest

_ALLOWED=frozenset({'SEARCH','CODE','DATA','PC_CONTROL'})

@dataclass(frozen=True)
class LongRunningSubmission:
    job_id: str
    request: CapabilityRequest
    text: str
    def __post_init__(self):
        if not self.job_id or not self.text: raise ValueError('job id and work text required')
        if not self.request.long_running: raise ValueError('long-running request required')
        if self.request.capability not in _ALLOWED: raise PermissionError('capability not allowed for long-running submission')

class DurableSubmissionPort:
    def submit(self,submission): raise NotImplementedError
    def status(self,job_id): raise NotImplementedError

@dataclass
class LongRunningWorkService:
    port: DurableSubmissionPort
    def submit(self,submission:LongRunningSubmission): return self.port.submit(submission)
    def status(self,job_id:str):
        if not job_id: raise ValueError('job id required')
        return self.port.status(job_id)
