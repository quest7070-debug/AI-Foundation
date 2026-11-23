"""Hatchet implementation of the explicit LongRunningWorkService port."""
from __future__ import annotations
import json,sqlite3,time
from hatchet_sdk.types.trigger import TriggerWorkflowOptions
from hatchet_sdk.exceptions import IdempotencyCollisionError
from hatchet_sdk import V1TaskStatus
from pathlib import Path
from .long_running import DurableSubmissionPort,LongRunningSubmission

class HatchetRunStore:
    """Small durable job->Hatchet run index; Hatchet remains run-state authority."""
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path) as d:
            d.execute('PRAGMA journal_mode=WAL');d.execute('CREATE TABLE IF NOT EXISTS hatchet_runs(job_id TEXT PRIMARY KEY,workflow_run_id TEXT NOT NULL,updated_at REAL NOT NULL)')
    def put(self,job_id,run_id):
        with sqlite3.connect(self.path) as d:d.execute('INSERT INTO hatchet_runs VALUES(?,?,?) ON CONFLICT(job_id) DO UPDATE SET workflow_run_id=excluded.workflow_run_id,updated_at=excluded.updated_at',(job_id,run_id,time.time()))
    def get(self,job_id):
        with sqlite3.connect(self.path) as d:r=d.execute('SELECT workflow_run_id FROM hatchet_runs WHERE job_id=?',(job_id,)).fetchone()
        return r[0] if r else None
    def forget(self,job_id):
        with sqlite3.connect(self.path) as d:d.execute('DELETE FROM hatchet_runs WHERE job_id=?',(job_id,))

class HatchetSubmissionPort(DurableSubmissionPort):
    def __init__(self,client,workflow_name='ai-foundation-long-running',run_store=None):
        if not workflow_name: raise ValueError('workflow name required')
        self.client=client;self.workflow_name=workflow_name;self.run_store=run_store
        # Compatibility-only fallback for isolated callers that have not supplied a
        # durable store. Production wiring must supply HatchetRunStore.
        self._runs={} if run_store is None else None
    def _put(self,job_id,run_id):
        if self.run_store is not None:self.run_store.put(job_id,run_id)
        else:self._runs[job_id]=run_id
    def _get(self,job_id):return self.run_store.get(job_id) if self.run_store is not None else self._runs.get(job_id)
    def submit(self,submission:LongRunningSubmission):
        payload={'job_id':submission.job_id,'capability':submission.request.capability,'owner_id':submission.request.owner_id,'text':submission.text}
        body=payload
        # Hatchet's workflow trigger has a native idempotency key. Binding it to the
        # Foundation job identity closes the remote-success/local-index crash window:
        # a replay resolves the existing run instead of creating a second workflow.
        try:
            workflow=self.client.workflow(name=self.workflow_name,input_validator=dict)
            ref=workflow.run_no_wait(body,options=TriggerWorkflowOptions(key=submission.job_id))
            run_id=ref.workflow_run_id
        except IdempotencyCollisionError as e:
            run_id=e.existing_run_external_id
        self._put(submission.job_id,run_id);return submission.job_id
    def status(self,job_id):
        run_id=self._get(job_id)
        if run_id is None:return 'UNKNOWN'
        state=self.client.runs.get_status(run_id)
        result=None
        if state == V1TaskStatus.COMPLETED:
            result=self.client.runs.get_result(run_id)
        return {
            'job_id':job_id,
            'workflow_run_id':run_id,
            'state':getattr(state,'value',str(state)),
            'result':result,
        }
