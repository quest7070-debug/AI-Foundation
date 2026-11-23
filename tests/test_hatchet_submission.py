import json
import pytest
from hatchet_sdk import V1TaskStatus

from ai_foundation.capability_request import CapabilityRequest
from ai_foundation.hatchet_submission import HatchetSubmissionPort
from ai_foundation.long_running import LongRunningSubmission,LongRunningWorkService


class Ref:
    def __init__(self,run_id):
        self.workflow_run_id=run_id


class Workflow:
    def __init__(self,client):
        self.client=client

    def run_no_wait(self,payload,options=None):
        self.client.calls.append(
            (self.client.selected_workflow,payload,options)
        )
        return Ref("wr-1")


class Runs:
    def get_run_ref(self,run_id):
        return Ref(run_id)

    def get_status(self,run_id):
        return V1TaskStatus.RUNNING

    def get_result(self,run_id):
        raise AssertionError('result must not be read before completion')


class C:
    def __init__(self):
        self.calls=[]
        self.selected_workflow=None
        self.runs=Runs()

    def workflow(self,name,input_validator=None):
        self.selected_workflow=name
        self.input_validator=input_validator
        return Workflow(self)


def test_hatchet_submission_serializes_minimal_non_authority_payload():
    c=C()
    p=HatchetSubmissionPort(c)
    svc=LongRunningWorkService(p)

    r=CapabilityRequest(
        'CODE',
        owner_id='u',
        repo_root='/trusted/repo',
        long_running=True,
    )

    assert svc.submit(
        LongRunningSubmission('j1',r,'inspect')
    )=='j1'

    assert len(c.calls)==1

    name,payload,options=c.calls[0]

    assert name=='ai-foundation-long-running'

    body=payload

    assert isinstance(body,dict)
    assert body=={
        'job_id':'j1',
        'capability':'CODE',
        'owner_id':'u',
        'text':'inspect',
    }

    assert options.key=='j1'


def test_durable_run_index_survives_port_reconstruction_and_can_be_forgotten(
    tmp_path,
):
    from ai_foundation.hatchet_submission import HatchetRunStore

    c=C()
    store=HatchetRunStore(tmp_path/'hatchet-runs.sqlite')

    p=HatchetSubmissionPort(c,run_store=store)
    svc=LongRunningWorkService(p)

    r=CapabilityRequest(
        'CODE',
        owner_id='u',
        repo_root='/trusted/repo',
        long_running=True,
    )

    svc.submit(LongRunningSubmission('j2',r,'inspect'))

    rebuilt=HatchetSubmissionPort(c,run_store=store)

    status=rebuilt.status('j2')

    assert status['job_id']=='j2'
    assert status['workflow_run_id']=='wr-1'

    store.forget('j2')

    assert rebuilt.status('j2')=='UNKNOWN'


def test_idempotency_collision_recovers_existing_remote_run(tmp_path):
    from ai_foundation.hatchet_submission import HatchetRunStore
    from hatchet_sdk.exceptions import IdempotencyCollisionError

    class CollisionWorkflow(Workflow):
        def run_no_wait(self,payload,options=None):
            self.client.calls.append(
                (self.client.selected_workflow,payload,options)
            )
            raise IdempotencyCollisionError('wr-existing')

    class CollisionClient(C):
        def workflow(self,name,input_validator=None):
            self.selected_workflow=name
            self.input_validator=input_validator
            return CollisionWorkflow(self)

    c=CollisionClient()
    store=HatchetRunStore(tmp_path/'runs.sqlite')

    p=HatchetSubmissionPort(c,run_store=store)

    r=CapabilityRequest(
        'DATA',
        owner_id='u',
        data_operation='json_summary',
        long_running=True,
    )

    assert p.submit(
        LongRunningSubmission('job-stable',r,'[1,2]')
    )=='job-stable'

    assert store.get('job-stable')=='wr-existing'

    assert len(c.calls)==1
    assert c.calls[0][2].key=='job-stable'


def test_unknown_status():
    assert HatchetSubmissionPort(C()).status('missing')=='UNKNOWN'


def test_status_reads_remote_hatchet_state_and_completed_result(tmp_path):
    from ai_foundation.hatchet_submission import HatchetRunStore

    class CompletedRuns:
        def get_status(self,run_id):
            assert run_id=='wr-complete'
            return V1TaskStatus.COMPLETED

        def get_result(self,run_id):
            assert run_id=='wr-complete'
            return {
                'status':'VERIFIED_COMPLETE',
                'result':'ok',
            }

    c=C()
    c.runs=CompletedRuns()

    store=HatchetRunStore(tmp_path/'status.sqlite')
    store.put('job-complete','wr-complete')

    p=HatchetSubmissionPort(c,run_store=store)

    assert p.status('job-complete')=={
        'job_id':'job-complete',
        'workflow_run_id':'wr-complete',
        'state':'COMPLETED',
        'result':{
            'status':'VERIFIED_COMPLETE',
            'result':'ok',
        },
    }


def test_status_does_not_request_result_before_completion(tmp_path):
    from ai_foundation.hatchet_submission import HatchetRunStore

    class RunningRuns:
        def get_status(self,run_id):
            assert run_id=='wr-running'
            return V1TaskStatus.RUNNING

        def get_result(self,run_id):
            raise AssertionError('result must not be read before completion')

    c=C()
    c.runs=RunningRuns()

    store=HatchetRunStore(tmp_path/'running.sqlite')
    store.put('job-running','wr-running')

    p=HatchetSubmissionPort(c,run_store=store)

    status=p.status('job-running')

    assert status['job_id']=='job-running'
    assert status['workflow_run_id']=='wr-running'
    assert status['state']=='RUNNING'
    assert status['result'] is None
