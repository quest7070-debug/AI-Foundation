"""Bounded audit regressions F01-F07; no services, model calls or external effects."""
import contextlib
import hashlib
import json
import threading
from types import SimpleNamespace

import pytest

from ai_foundation.core import CanonContract, GuardState, TaskPlan
from ai_foundation.guard import GuardCore
from ai_foundation.durable_work import SQLiteWorkStore, DurableWorkRunner
from ai_foundation.work_runtime import DurableWorkRuntimeCall
from ai_foundation.orchestration import WorkStatus
from ai_foundation.klm_drive_input import DriveState
from ai_foundation.klm_drive_work import IntakeQueue, IdleKlmWorker, DevObservation, inbox_records
from ai_foundation.coding_adapter import build_coding_specialist
from ai_foundation.capability_request import CapabilityRequest
from ai_foundation.long_running_authority import LongRunningAuthorityStore, DurableLongRunningExecutor
from ai_foundation.task_intake import TaskIntake


def test_f01_klm_defer_does_not_resurrect_completed_work(tmp_path):
    state=DriveState(SQLiteWorkStore(tmp_path / 'klm.sqlite'))
    queue=IntakeQueue(state)
    queue.enqueue(inbox_records([['task'],['example']],owner='audit-owner')[0])
    job=queue.next()['job_id']
    entered,release=threading.Event(),threading.Event()
    def observation():
        entered.set()
        assert release.wait(5)
        return DevObservation(1,0,True,100)
    worker=IdleKlmWorker(queue,observe_dev=observation,
                         lease=SimpleNamespace(hold=lambda **kw: contextlib.nullcontext()),
                         compute_idle=lambda: True,clock=lambda: 100)
    outcomes=[]
    t=threading.Thread(target=lambda: outcomes.append(worker.tick(read_source=None,handler=lambda *a,**kw: None)))
    t.start()
    assert entered.wait(5)
    assert state.work.claim_not_running(job,0)
    state.work.set(job,0,WorkStatus.VERIFIED,'verified-by-other')
    release.set()
    t.join(5)
    assert not t.is_alive()
    assert outcomes==['ALREADY_CLAIMED']
    assert state.work.load(job)[0].status is WorkStatus.VERIFIED
    assert queue.next() is None


def test_f02_guard_failed_readback_stops_dependent_step(tmp_path):
    class WrongReadback:
        def execute(self,plan): pass
        def observe(self,plan): return 'actual'
    store=SQLiteWorkStore(tmp_path / 'work.sqlite')
    guard=GuardCore(GuardState())
    plan=TaskPlan('guard-run','write','audit-target',text='expected',canon_revision='v1')
    dependent=[]
    with pytest.raises(RuntimeError,match='FAILED'):
        DurableWorkRuntimeCall(DurableWorkRunner(store)).run('workflow',[
            ('write',lambda:guard.execute(plan,CanonContract('audit','v1'),WrongReadback(),'expected')),
            ('dependent',lambda:dependent.append(True)),
        ])
    assert not dependent
    assert store.load('workflow')[0].status is WorkStatus.FAILED


def test_f03_code_tests_host_suite_not_edited_source(tmp_path):
    repo=tmp_path / 'repo'
    (repo/'src').mkdir(parents=True)
    (repo/'tests').mkdir()
    source=repo/'src/value.py'
    source.write_text('VALUE = 1\n')
    (repo/'tests/test_value.py').write_text(
        'import runpy\nfrom pathlib import Path\n'
        'def test_value():\n'
        ' assert runpy.run_path(str(Path(__file__).parents[1]/"src/value.py"))["VALUE"] == 1\n')
    class Files:
        def observe(self,plan): return source.read_text()
        def execute(self,plan): source.write_text(plan.text)
    specialist=build_coding_specialist(
        CapabilityRequest('CODE',repo_root=str(repo)),GuardCore(GuardState()),
        Files(),'code-run')
    assert specialist.tests.acceptance_path('src/value.py') == repo/'tests/test_value.py'
    result=specialist.apply_verified_change('src/value.py','VALUE = 2\n')
    # The change is Guard-verified, but independent tests correctly fail.
    assert source.read_text()=='VALUE = 2\n'
    assert result.write_result=='VERIFIED_COMPLETE'
    assert 'after=FAILED:' in result.test_result
    assert result.verified is False


def test_f03_unmapped_source_uses_bound_suite_and_denies_escaped_tests(tmp_path):
    from ai_foundation.coding_adapter import PytestPort
    repo=tmp_path/'repo'
    (repo/'src').mkdir(parents=True)
    (repo/'tests').mkdir()
    source=repo/'src/unknown.py'
    source.write_text('pass\n')
    port=PytestPort(str(repo))
    assert port.acceptance_path('src/unknown.py')==repo/'tests'
    assert port.timeout>=180
    empty=tmp_path/'no-tests'
    empty.mkdir()
    with pytest.raises(PermissionError,match='NO_HOST_ACCEPTANCE_SUITE'):
        PytestPort(str(empty)).acceptance_path('src/anything.py')
    external=tmp_path/'external.py'
    external.write_text('def test_escape(): assert False\n')
    (repo/'tests/test_unknown.py').symlink_to(external)
    with pytest.raises(PermissionError,match='outside bound repository'):
        port.acceptance_path('src/unknown.py')


def test_f04_data_backend_survives_authority_roundtrip(tmp_path):
    authority=LongRunningAuthorityStore(tmp_path / 'authority.sqlite')
    req=CapabilityRequest('DATA',owner_id='audit-owner',data_backend='duckdb',long_running=True)
    authority.put('data-job',req)
    restored=authority.get('data-job','audit-owner','DATA')
    assert restored==req
    authority.put('data-job',req)


def test_f04_legacy_exact_replay_stays_idempotent_without_backend_grant(tmp_path):
    import sqlite3
    import time
    authority=LongRunningAuthorityStore(tmp_path / 'legacy.sqlite')
    req=CapabilityRequest('DATA',owner_id='audit-owner',
                          data_operation='json_summary',long_running=True)
    legacy={k:getattr(req,k) for k in (
        'capability','owner_id','repo_root','file_read_root','file_write_root',
        'data_operation','pc_target','long_running','attachment_ids')}
    legacy['attachment_ids']=list(legacy['attachment_ids'])
    with sqlite3.connect(authority.path) as db:
        db.execute('INSERT INTO long_running_authority VALUES(?,?,?,?)',
                   ('legacy-job',req.owner_id,json.dumps(legacy,sort_keys=True),time.time()))
    authority.put('legacy-job',req)
    assert authority.get('legacy-job',req.owner_id,'DATA')==req
    with pytest.raises(PermissionError,match='replay mismatch'):
        authority.put('legacy-job',CapabilityRequest(
            'DATA',owner_id='audit-owner',data_backend='duckdb',long_running=True))


def test_f05_long_running_code_failure_not_promoted(tmp_path):
    authority=LongRunningAuthorityStore(tmp_path / 'authority.sqlite')
    req=CapabilityRequest('CODE',owner_id='audit-owner',repo_root=str(tmp_path),long_running=True)
    authority.put('code-job',req)
    class FailedCode:
        def execute(self,request,text,run_id):
            return json.dumps({'operation':'change','status':'FAILED_VERIFICATION',
                               'verification':'before=PASS; after=FAILED: regression'})
    outer=DurableLongRunningExecutor(authority,FailedCode())
    outcome=outer.execute_long_running('code-job','CODE','audit-owner','{}')
    assert outcome['status']=='FAILED_VERIFICATION'


def test_f06_cancel_wins_over_delayed_completion(tmp_path):
    intake=TaskIntake(tmp_path / 'intake.sqlite')
    job=intake.submit('audit task').job_id
    entered,release=threading.Event(),threading.Event()
    outcome=[]
    def slow_runner(receipt):
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(status='VERIFIED_COMPLETE',result='late')
    t=threading.Thread(target=lambda:outcome.append(intake.execute(job,slow_runner)))
    t.start()
    assert entered.wait(5)
    assert intake.cancel(job)
    release.set()
    t.join(5)
    assert not t.is_alive()
    assert outcome==['CANCELLED']
    assert intake.store.load(job)[0].status is WorkStatus.CANCELLED


def test_f07_sparse_drive_change_does_not_erase_metadata(tmp_path):
    state=DriveState(SQLiteWorkStore(tmp_path / 'drive.sqlite'))
    complete={'id':'audit-file','name':'name','mimeType':'text/plain','parents':['root'],
              'version':'1','md5Checksum':'012345','owners':[{'displayName':'synthetic'}],
              'webViewLink':'https://example.invalid/synthetic','permissions':[],'shared':False}
    assert state.observe(complete)=='DISCOVERED'
    sparse={k:v for k,v in complete.items() if k not in {'md5Checksum','owners','webViewLink'}}
    assert state.observe(sparse)=='NO_CHANGE'
    with state.db() as db:
        value=json.loads(db.execute('SELECT body FROM klm_drive_objects WHERE id=?',('audit-file',)).fetchone()[0])
    assert value['content_checksum']=='012345'
    assert value['owners']==complete['owners']
    assert value['url']==complete['webViewLink']
