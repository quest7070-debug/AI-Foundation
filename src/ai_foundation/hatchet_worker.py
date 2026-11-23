"""Explicit Hatchet worker boundary for owner-approved long-running work.

Hatchet carries only identity/text routing metadata. Host authority is re-resolved by
Foundation from durable state; repo/file/PC grants are never accepted from workflow input.
"""
from __future__ import annotations
from dataclasses import dataclass

_ALLOWED=frozenset({'SEARCH','CODE','DATA','PC_CONTROL'})

@dataclass(frozen=True)
class LongRunningWorkItem:
    job_id:str
    capability:str
    owner_id:str
    text:str
    @classmethod
    def parse(cls,value):
        if not isinstance(value,dict): raise ValueError('invalid long-running input')
        allowed={'job_id','capability','owner_id','text'}
        if set(value)-allowed: raise ValueError('unexpected long-running input field')
        item=cls(str(value.get('job_id','')),str(value.get('capability','')).upper(),str(value.get('owner_id','')),str(value.get('text','')))
        if not item.job_id or not item.text: raise ValueError('job id and work text required')
        if item.capability not in _ALLOWED: raise PermissionError('capability not allowed')
        if len(item.owner_id)>256: raise ValueError('owner id too long')
        return item

class LongRunningWorkerHandler:
    """Thin worker adapter; executor owns durable Foundation/Guard authority."""
    def __init__(self,executor): self.executor=executor
    def __call__(self,value):
        item=LongRunningWorkItem.parse(value)
        return self.executor.execute_long_running(item.job_id,item.capability,item.owner_id,item.text)

def build_workflow(hatchet,handler,name='ai-foundation-long-running'):
    if not name: raise ValueError('workflow name required')
    workflow=hatchet.workflow(name=name,input_validator=dict)
    @workflow.task(name='execute',retries=0)
    def execute(input,ctx) -> dict:
        return handler(input)
    return workflow

def build_worker(hatchet,handler,*,worker_name='ai-foundation-long-running-worker',workflow_name='ai-foundation-long-running'):
    workflow=build_workflow(hatchet,handler,workflow_name)
    return hatchet.worker(worker_name,workflows=[workflow])
