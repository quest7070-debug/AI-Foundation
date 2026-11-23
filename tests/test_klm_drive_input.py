import json
import hashlib
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.orchestration import WorkStatus
from ai_foundation.klm_drive_input import DriveState, Page, FOLDER, CursorExpired, metadata, ReadOnlyDriveAPI, digest
from ai_foundation.klm_drive_work import (IntakeQueue, SourceVerifiedRetryIntents, LegacyRehydrateQueue, IdleKlmWorker, DevObservation,
    inbox_records, inbox_update_plan, klm_proposals, read_development_state,read_inbox_source)
from ai_foundation.klm_drive_runtime import OwnerDriveHTTP, local_compute_unoccupied
from ai_foundation.knowledge_lifecycle import Meaning, ReadonlyReceiptJournal


def file(sid,version='1',parent='root',mime='text/plain'):
    return {'id':sid,'name':sid,'mimeType':mime,'parents':[parent],'version':version,
            'modifiedTime':'2026-11-07T00:00:00Z','shared':False,'permissions':[]}


@pytest.fixture
def state(tmp_path): return DriveState(SQLiteWorkStore(tmp_path/'work.sqlite'))


class Pages:
    def __init__(self,rows): self.rows=rows; self.calls=[]
    def list_children(self,folder,cursor=None):
        self.calls.append((folder,cursor))
        value=self.rows[(folder,cursor)]
        if isinstance(value,Exception): raise value
        return value


def test_recursive_multipage_restart_and_idempotent_source_events(state):
    api=Pages({('root',None):Page((file('child',mime=FOLDER),),'p2'),
        ('root','p2'):Page((file('f2'),)),('child',None):Page((file('f3',parent='child'),))})
    scan=state.begin_scan(['root'],'stable')
    assert state.scan(api,scan,page_budget=1)['coverage']=='PARTIAL'
    restored=DriveState(SQLiteWorkStore(state.path))
    assert restored.begin_scan(['root'],'stable')==scan
    result=restored.scan(api,scan)
    assert (result['coverage'],result['objects'],result['folders'],result['pages'])==('COMPLETE',3,2,3)
    assert api.calls.count(('root',None))==1
    assert restored.observe(file('f2'))=='NO_CHANGE'
    with state.db() as db: assert db.execute('SELECT COUNT(*) FROM klm_drive_events').fetchone()[0]==3


def test_failure_preserves_cursor_and_resumes_same_page(state):
    api=Pages({('root',None):Page((file('a'),),'p2'),('root','p2'):OSError('secret-token')})
    scan=state.begin_scan(['root'])
    first=state.scan(api,scan)
    assert first['coverage']=='PARTIAL' and first['checkpoints'][0]['cursor']=='p2'
    assert 'secret-token' not in json.dumps(first)
    api.rows[('root','p2')]=Page((file('b'),))
    assert state.scan(api,scan)['coverage']=='COMPLETE'


def test_scan_does_not_persist_raw_provider_valueerror_text(state):
    api = Pages({('root', None): ValueError('PRIVATE_TOKEN_FROM_PROVIDER')})
    scan = state.begin_scan(['root'])
    report = state.scan(api, scan)
    assert report['checkpoints'][0]['status'] == 'RETRY'
    assert report['checkpoints'][0]['reason'] == 'ValueError'
    assert 'PRIVATE_TOKEN_FROM_PROVIDER' not in json.dumps(report)
    assert b'PRIVATE_TOKEN_FROM_PROVIDER' not in state.path.read_bytes()
    api.rows[('root', None)] = Page((file('a'),))
    assert state.scan(api, scan)['coverage'] == 'COMPLETE'


def test_no_page_is_unknown_not_empty_complete(state):
    api=Pages({('root',None):PermissionError('not allowed')})
    result=state.scan(api,state.begin_scan(['root']))
    assert result['coverage']=='UNKNOWN' and result['objects']==0


@pytest.mark.parametrize('pages',[{('root',None):Page((),terminal_proven=False)},
    {('root',None):Page((), 'p2',False),('root','p2'):Page(())},
    {('root',None):Page((), 'same'),('root','same'):Page((), 'same')}])
def test_unproven_or_repeated_cursor_never_complete(state,pages):
    assert state.scan(Pages(pages),state.begin_scan(['root']))['coverage']=='PARTIAL'


def test_mutating_same_id_across_pages_blocks_finalization(state):
    api=Pages({('root',None):Page((file('a'),),'p2'),('root','p2'):Page((file('a','2'),))})
    result=state.scan(api,state.begin_scan(['root']))
    assert result['coverage']=='PARTIAL'
    assert result['checkpoints'][0]['reason']=='REVISION_CHANGED_DURING_SCAN'


def test_polling_missing_is_not_deletion_and_partial_does_not_claim_absence(state):
    scan=state.begin_scan(['root'])
    state.scan(Pages({('root',None):Page((),terminal_proven=False)}),scan)
    assert state.missing_candidates(['old'],scan)[0]['status']=='UNKNOWN_COVERAGE'
    scan2=state.begin_scan(['root'])
    state.scan(Pages({('root',None):Page(())}),scan2)
    assert state.missing_candidates(['old'],scan2)[0]['status']=='MISSING_FROM_SCOPE_NOT_PROVEN_DELETED'


def test_raw_adapter_is_get_only_and_checks_provider_incomplete_search():
    calls=[]
    api=ReadOnlyDriveAPI(lambda path,params:(calls.append((path,params)) or {'files':[],'incompleteSearch':True}))
    assert not api.list_children('root').terminal_proven
    assert calls[0][0]=='/drive/v3/files'
    with pytest.raises(ValueError): api.list_children("root' or trashed = true")
    with pytest.raises(PermissionError): OwnerDriveHTTP(lambda:'unused')('/drive/v3/files/../permissions',{})
    assert not hasattr(api,'update')


@pytest.mark.parametrize('path', [
    '/drive/v3/files/',
    '/drive/v3/files/a/permissions',
    '/drive/v3/files/a/export',
    '/drive/v3/files/a#fragment',
    '/drive/v3/files/a%2Fpermissions',
    '/drive/v3/files/a%3Falt%3Dmedia',
    '/drive/v3/files/a?alt=media',
    '/drive/v3/files/a\\nAuthorization: injected',
    '/drive/v3/files/' + 'a' * 161,
    '/drive/v3/files//a',
    '/drive/v3/files/../permissions',
])
def test_owner_drive_get_rejects_unscoped_subresources_before_token(path):
    def forbidden():
        pytest.fail('invalid Drive path acquired a token')
    client = OwnerDriveHTTP(forbidden)
    with pytest.raises(PermissionError, match='READ_ONLY_DRIVE_PATH_REQUIRED'):
        client(path, {})
    assert client.allowed('/drive/v3/files/a_B-90')
    assert client.allowed('/drive/v3/files')
    assert client.allowed('/drive/v3/changes')
    assert client.allowed('/drive/v3/changes/startPageToken')


def test_metadata_missing_revision_and_sharing_remains_unknown():
    row=metadata({'id':'a','title':'a','modified_time':'2026-11-07T00:00:00Z'})
    assert row['revision_quality']=='METADATA_ONLY' and row['permission_coverage']=='UNKNOWN'
    assert row['owners'] is None


def test_same_native_revision_with_changed_metadata_is_conflict(state):
    assert state.observe(file('a'))=='DISCOVERED'
    changed=file('a');changed['shared']=True
    assert state.observe(changed)=='REVISION_CONFLICT'


def test_cursor_expiry_full_resync_then_replay_and_restart(state):
    class API:
        def start_cursor(self): return 'before-scan'
        def changes(self,token): raise CursorExpired()
    api=API()
    assert state.poll_changes(api,'owner',{'a'})=='RESCAN_REQUIRED'
    scan=state.begin_scan(['root'])
    assert state.finish_resync(api,'owner',scan,start_cursor='before-scan')=='PARTIAL'
    state.scan(Pages({('root',None):Page((file('a'),))}),scan)
    assert state.finish_resync(api,'owner',scan,start_cursor='before-scan')=='REPLAY_REQUIRED'
    assert state.poll_changes(api,'owner',{'a'})=='RESCAN_REQUIRED'
    restored=DriveState(SQLiteWorkStore(state.path))
    assert restored.poll_changes(api,'owner',{'a'})=='RESCAN_REQUIRED'


def test_changes_duplicate_multiupdates_move_and_out_of_scope(state):
    scan=state.begin_scan(['root']);state.scan(Pages({('root',None):Page(())}),scan)
    class API:
        def changes(self,token):
            if token=='c1': return Page(({'fileId':'a','file':file('a')},{'fileId':'a','file':file('a')}),'c2')
            return Page(({'fileId':'a','file':file('a','2',parent='other')},),new_start_cursor='c3')
    api=API();state.finish_resync(api,'owner',scan,start_cursor='c1')
    assert state.poll_changes(api,'owner',{'a'})=='COMPLETE'
    with state.db() as db:
        assert db.execute('SELECT COUNT(*) FROM klm_drive_events').fetchone()[0]==2
        assert db.execute("SELECT kind FROM klm_drive_events WHERE kind='MOVED'").fetchone()
    api.changes=lambda token:Page(({'fileId':'foreign','file':file('foreign')},),new_start_cursor='c4')
    assert state.poll_changes(api,'owner',{'a'})=='RESCAN_REQUIRED'
    with state.db() as db: assert not db.execute("SELECT 1 FROM klm_drive_objects WHERE id='foreign'").fetchone()


@pytest.mark.parametrize('event', [
    {'fileId': 'a', 'file': file('foreign')},
    {'fileId': 'a'},
    {'fileId': 'a', 'removed': 'false', 'file': file('a')},
    {'fileId': 'a', 'file': None},
    {'fileId': 'a', 'file': {'id': 'foreign'}},
    {'file': file('a')},
])
def test_changes_inconsistent_or_missing_identity_never_advances_current(state, event):
    with state.db() as db:
        db.execute('INSERT INTO klm_drive_cursors VALUES(?,?,?,?)',
                   ('owner', 'before', 'PENDING', 0))
    api = SimpleNamespace(changes=lambda token: Page((event,), new_start_cursor='after'))
    assert state.poll_changes(api, 'owner', {'a'}) == 'RESCAN_REQUIRED'
    with state.db() as db:
        cursor = db.execute(
            'SELECT status FROM klm_drive_cursors WHERE owner_scope=?', ('owner',)
        ).fetchone()[0]
        assert cursor == 'RESCAN_REQUIRED'
        assert not db.execute(
            "SELECT id FROM klm_drive_objects WHERE id IN ('foreign','a')"
        ).fetchone()


def test_changes_network_failure_keeps_cursor_and_removed_is_ambiguous(state):
    with state.db() as db: db.execute('INSERT INTO klm_drive_cursors VALUES(?,?,?,?)',('owner','c1','CURRENT',0))
    api=SimpleNamespace(changes=lambda token:(_ for _ in ()).throw(OSError()))
    assert state.poll_changes(api,'owner',{'a'})=='PARTIAL'
    with state.db() as db: assert db.execute('SELECT token FROM klm_drive_cursors').fetchone()[0]=='c1'
    api.changes=lambda token:Page(({'fileId':'a','removed':True},),new_start_cursor='c2')
    assert state.poll_changes(api,'owner',{'a'})=='COMPLETE'
    with state.db() as db: assert db.execute('SELECT kind FROM klm_drive_events').fetchone()[0]=='REMOVED_OR_INACCESSIBLE'


def records(): return inbox_records([['思いつき・要望','状態'],['private text','保留']],owner='owner')


def test_legacy_inbox_reorder_duplicate_restart_and_no_raw_copy(state):
    a=records()[0];queue=IntakeQueue(state)
    assert queue.enqueue(a)=='STAGED'
    assert IntakeQueue(DriveState(SQLiteWorkStore(state.path))).enqueue(a)=='ALREADY_STAGED'
    assert b'private text' not in state.path.read_bytes()
    two=inbox_records([['思いつき・要望','状態'],['other','保留'],['private text','保留'],['private text','保留']],owner='owner')
    assert len(two)==2 and a['intake_id']==two[1]['intake_id']
    assert not inbox_update_plan(two)[0]['effect_authorized']


def test_explicit_row_revision_change_cancels_old_pending_work(state):
    rows=[['intake_id','状態'],['stable','pending']]
    queue=IntakeQueue(state);before=inbox_records(rows,owner='owner')[0];queue.enqueue(before)
    rows[1][1]='changed';after=inbox_records(rows,owner='owner')[0];queue.enqueue(after)
    assert queue.work.load('klm-drive:'+before['intake_id'])[0].status==WorkStatus.CANCELLED


class Busy(RuntimeError): pass
class Lease:
    def __init__(self,busy=False): self.busy=busy;self.held=False
    @contextmanager
    def hold(self,*,max_wait_s=0):
        if self.busy: raise Busy()
        self.held=True
        try: yield 123
        finally: self.held=False


def worker(state,observations=None,compute=True,busy=False):
    queue=IntakeQueue(state);queue.enqueue(records()[0])
    idle=DevObservation(0,0,True,100)
    seq=iter(observations or [idle]*20)
    lease=Lease(busy)
    return IdleKlmWorker(queue,observe_dev=lambda:next(seq),lease=lease,
        compute_idle=lambda:compute,busy_types=(Busy,),clock=lambda:100)


def current(pointer): return {'revision':pointer['source_revision'],'sha256':hashlib.sha256(b'original').hexdigest(),'raw':b'original'}
def handler(pointer,source,*,deadline):
    atoms=klm_proposals(pointer,source,[(0,len(source['raw']),Meaning('observation','assertion','positive','item','state','pending'))])
    assert len(atoms)==1 and not atoms[0].execution_authority
    return {'result_ref':'sha256:'+digest([a.atom_id for a in atoms]),'execution_authority':False}


@pytest.mark.parametrize('obs',[DevObservation(1,0,True,100),DevObservation(0,1,True,100),
    DevObservation(0,0,False,100),DevObservation(0,0,True,1)])
def test_dev_pending_active_unknown_or_stale_defers(state,obs):
    assert worker(state,[obs]).tick(read_source=current,handler=handler)=='WAIT_DEV_IDLE'


@pytest.mark.parametrize('compute,busy',[(False,False),(True,True)])
def test_model_occupancy_or_lease_contention_defers(state,compute,busy):
    assert worker(state,compute=compute,busy=busy).tick(read_source=current,handler=handler)=='DEFER_COMPUTE_BUSY'


def test_issue_arriving_after_initial_idle_is_rechecked_under_lease(state):
    w=worker(state,[DevObservation(0,0,True,100),DevObservation(1,0,True,100)])
    assert w.tick(read_source=current,handler=handler)=='WAIT_DEV_IDLE'


def test_readonly_handoff_reuses_core_and_is_exactly_claimed_once(state):
    w=worker(state)
    assert w.tick(read_source=current,handler=handler)=='READ_ONLY_VERIFIED'
    assert w.tick(read_source=current,handler=handler)=='NO_INPUT'
    assert not w.lease.held
    assert b'original' not in state.path.read_bytes()


def test_source_changed_before_or_during_handler_never_verified(state):
    w=worker(state)
    assert w.tick(read_source=lambda p:{'revision':'new'},handler=handler)=='SOURCE_CHANGED'
    # distinct new intake for the independent after-handler check
    r=records()[0];r.update(source_revision='r2');r['intake_id']=digest((r['source_id'],r['record_id'],r['source_revision'],r['owner'],r['privacy_scope']));w.queue.enqueue(r)
    count=[0]
    def read(p):
        count[0]+=1;return {**current(p),'sha256':'b'*64 if count[0]>1 else current(p)['sha256']}
    assert w.tick(read_source=read,handler=handler)=='SOURCE_CHANGED'


def test_crash_running_claim_is_never_replayed_and_backlog_age_is_visible(state):
    w=worker(state);job=w.queue.next()['job_id'];w.work.claim_not_running(job,0)
    restored=IntakeQueue(DriveState(SQLiteWorkStore(state.path)))
    assert restored.next() is None
    backlog=restored.backlog(now=time.time()+10000)
    assert backlog['uncertain_running']==1 and backlog['oldest_age_s']>=10000


def test_failed_handler_is_not_retried_forever_and_no_bound_handler_does_not_run(state):
    w=worker(state)
    assert w.tick(read_source=current)=='HANDLER_UNBOUND'
    assert w.tick(read_source=current,handler=lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('secret')))=='FAILED'
    assert w.tick(read_source=current,handler=handler)=='NO_INPUT'
    assert b'secret' not in state.path.read_bytes()


def test_empty_queue_is_noop_even_without_compute_or_issue_observation(state):
    w=IdleKlmWorker(IntakeQueue(state),observe_dev=lambda:pytest.fail(),lease=None,compute_idle=lambda:pytest.fail())
    assert w.tick(read_source=pytest.fail)=='NO_INPUT'



def queued_only_worker(state, now, queue_key, *, compute=True):
    queue=IntakeQueue(state)
    queue.enqueue(records()[0])
    return IdleKlmWorker(
        queue,
        observe_dev=lambda:DevObservation(
            1,0,True,now[0],queue_fingerprint=queue_key[0]),
        lease=Lease(),
        compute_idle=lambda:compute,
        clock=lambda:now[0])


def test_unchanged_queued_only_dev_gets_bounded_klm_after_two_worker_periods(state):
    now=[100]
    fingerprint=['a'*64]
    w=queued_only_worker(state,now,fingerprint)
    assert w.tick(read_source=current,handler=handler)=='WAIT_DEV_IDLE'
    saved=json.loads(w.work.load(w.queue.next()['job_id'])[0].result)
    assert saved['dev_wait_since']==100
    assert saved['dev_queue_fingerprint']=='a'*64
    now[0]=699
    assert w.tick(read_source=current,handler=handler)=='WAIT_DEV_IDLE'
    now[0]=700
    assert w.tick(read_source=current,handler=handler)=='READ_ONLY_VERIFIED'
    assert w.tick(read_source=current,handler=handler)=='NO_INPUT'


def test_new_dev_ready_issue_resets_klm_grace_without_restarting_model(state):
    now=[100]
    fingerprint=['a'*64]
    w=queued_only_worker(state,now,fingerprint)
    assert w.tick(read_source=current,handler=handler)=='WAIT_DEV_IDLE'
    now[0]=700
    fingerprint[0]='b'*64
    assert w.tick(read_source=current,handler=handler)=='WAIT_DEV_IDLE'
    receipt=json.loads(w.work.load(w.queue.next()['job_id'])[0].result)
    assert receipt['dev_wait_since']==700
    assert receipt['dev_queue_fingerprint']=='b'*64
    now[0]=1300
    assert w.tick(read_source=current,handler=handler)=='READ_ONLY_VERIFIED'


def test_live_or_uncertain_dev_remains_priority_even_after_queued_only_wait(state):
    now=[100]
    fingerprint=['a'*64]
    queue=IntakeQueue(state)
    queue.enqueue(records()[0])
    mode=['queued']
    def observe():
        if mode[0]=='active':
            return DevObservation(1,1,True,now[0],queue_fingerprint=fingerprint[0])
        if mode[0]=='unknown':
            return DevObservation(1,0,False,now[0],queue_fingerprint=fingerprint[0])
        return DevObservation(1,0,True,now[0],queue_fingerprint=fingerprint[0])
    w=IdleKlmWorker(queue,observe_dev=observe,lease=Lease(),
                    compute_idle=lambda:True,clock=lambda:now[0])
    assert w.tick(read_source=current,handler=handler)=='WAIT_DEV_IDLE'
    now[0]=700
    mode[0]='active'
    assert w.tick(read_source=current,handler=handler)=='WAIT_DEV_IDLE'
    mode[0]='unknown'
    assert w.tick(read_source=current,handler=handler)=='WAIT_DEV_IDLE'
    mode[0]='queued'
    assert w.tick(read_source=current,handler=handler)=='WAIT_DEV_IDLE'
    now[0]=1300
    assert w.tick(read_source=current,handler=handler)=='READ_ONLY_VERIFIED'


def test_queued_only_dev_never_bypasses_real_compute_pressure(state):
    now=[100]
    fingerprint=['a'*64]
    w=queued_only_worker(state,now,fingerprint,compute=False)
    assert w.tick(read_source=current,handler=handler)=='WAIT_DEV_IDLE'
    now[0]=700
    assert w.tick(read_source=current,handler=handler)=='DEFER_COMPUTE_BUSY'
    assert w.work.load(w.queue.next()['job_id'])[0].status is WorkStatus.PLANNED



def test_compute_pressure_preserves_finished_grace_for_same_queue(state):
    now=[100]
    fingerprint=['a'*64]
    compute=[False]
    w=queued_only_worker(state,now,fingerprint,compute=False)
    w.compute_idle=lambda:compute[0]
    assert w.tick(read_source=current,handler=handler)=='WAIT_DEV_IDLE'
    now[0]=700
    assert w.tick(read_source=current,handler=handler)=='DEFER_COMPUTE_BUSY'
    saved=json.loads(w.work.load(w.queue.next()['job_id'])[0].result)
    assert saved['dev_wait_since']==100
    now[0]=701
    compute[0]=True
    assert w.tick(read_source=current,handler=handler)=='READ_ONLY_VERIFIED'




def test_readonly_handoff_reuses_core_and_is_exactly_claimed_once(state):
    w=worker(state)
    assert w.tick(read_source=current,handler=handler)=='READ_ONLY_VERIFIED'
    assert w.tick(read_source=current,handler=handler)=='NO_INPUT'
    assert not w.lease.held
    assert b'original' not in state.path.read_bytes()


def test_source_changed_before_or_during_handler_never_verified(state):
    w=worker(state)
    assert w.tick(read_source=lambda p:{'revision':'new'},handler=handler)=='SOURCE_CHANGED'
    # distinct new intake for the independent after-handler check
    r=records()[0];r.update(source_revision='r2');r['intake_id']=digest((r['source_id'],r['record_id'],r['source_revision'],r['owner'],r['privacy_scope']));w.queue.enqueue(r)
    count=[0]
    def read(p):
        count[0]+=1;return {**current(p),'sha256':'b'*64 if count[0]>1 else current(p)['sha256']}
    assert w.tick(read_source=read,handler=handler)=='SOURCE_CHANGED'


def test_crash_running_claim_is_never_replayed_and_backlog_age_is_visible(state):
    w=worker(state);job=w.queue.next()['job_id'];w.work.claim_not_running(job,0)
    restored=IntakeQueue(DriveState(SQLiteWorkStore(state.path)))
    assert restored.next() is None
    backlog=restored.backlog(now=time.time()+10000)
    assert backlog['uncertain_running']==1 and backlog['oldest_age_s']>=10000


def test_failed_handler_is_not_retried_forever_and_no_bound_handler_does_not_run(state):
    w=worker(state)
    assert w.tick(read_source=current)=='HANDLER_UNBOUND'
    assert w.tick(read_source=current,handler=lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('secret')))=='FAILED'
    assert w.tick(read_source=current,handler=handler)=='NO_INPUT'
    assert b'secret' not in state.path.read_bytes()


def test_empty_queue_is_noop_even_without_compute_or_issue_observation(state):
    w=IdleKlmWorker(IntakeQueue(state),observe_dev=lambda:pytest.fail(),lease=None,compute_idle=lambda:pytest.fail())
    assert w.tick(read_source=pytest.fail)=='NO_INPUT'

def legacy_record(state):
    original = records()[0]
    queue = IntakeQueue(state)
    assert queue.enqueue(original) == 'STAGED'
    state.work.set('klm-drive:' + original['intake_id'], 0,
                   WorkStatus.VERIFIED,
                   json.dumps({'execution_authority':False}))
    ReadonlyReceiptJournal(state.path)
    source_hash = current(original)['sha256']
    with state.db() as db:
        db.execute("INSERT INTO klm_atoms VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   ('a'*64, 'gdrive', original['source_id'], original['record_id'],
                    original['source_revision'], 'drive-inbox', original['privacy_scope'],
                    source_hash, 'b'*64, 0, 8, 'c'*64, 'legacy'))
    return original, source_hash


def test_legacy_verified_source_rehydrates_once_without_changing_original(state):
    original, expected = legacy_record(state)
    q = LegacyRehydrateQueue(state)
    selected = q.next()
    assert selected['source_revision'] == original['source_revision']
    assert selected['expected_source_sha256'] == expected
    assert selected['job_id'].startswith('klm-legacy-review:')
    assert state.work.load('klm-drive:' + original['intake_id'])[0].status is WorkStatus.VERIFIED
    idle = DevObservation(0,0,True,100)
    worker = IdleKlmWorker(q, observe_dev=lambda:idle, lease=Lease(),
                           compute_idle=lambda:True, clock=lambda:100)
    assert worker.tick(
        read_source=current,
        handler=lambda p, c, *, deadline: {
            'execution_authority':False,
            'result_ref':'klm-atoms-sha256:' + 'd'*64
        }) == 'READ_ONLY_VERIFIED'
    assert q.next() is None
    assert state.work.load('klm-drive:' + original['intake_id'])[0].status is WorkStatus.VERIFIED
    assert state.work.load(selected['job_id'])[0].status is WorkStatus.VERIFIED


def test_legacy_rehydrate_rejects_changed_bytes_before_model_call(state):
    original, expected = legacy_record(state)
    q = LegacyRehydrateQueue(state)
    selected = q.next()
    worker = IdleKlmWorker(
        q, observe_dev=lambda:DevObservation(0,0,True,100),
        lease=Lease(), compute_idle=lambda:True, clock=lambda:100)
    changed = b'new text'
    def stale(_):
        return {'revision':original['source_revision'],
                'sha256':hashlib.sha256(changed).hexdigest(), 'raw':changed}
    assert worker.tick(read_source=stale, handler=lambda *a, **k:pytest.fail()) == 'SOURCE_CHANGED'
    assert state.work.load(selected['job_id'])[0].status is WorkStatus.CANCELLED
    assert state.work.load('klm-drive:' + original['intake_id'])[0].status is WorkStatus.VERIFIED



def test_gui_owner_service_verifies_and_requeues_only_one_failed_intent(state):
    original = records()[0]
    queue = IntakeQueue(state)
    assert queue.enqueue(original) == 'STAGED'
    key = 'klm-drive:' + original['intake_id']
    state.work.set(key, 0, WorkStatus.FAILED,
                   json.dumps({'error_type':'ValueError',
                               'phase':'MODEL_AND_DERIVATION'}))
    intent = 'klm-retry-intent:' + original['intake_id']
    state.work.ensure(intent, ['klm-source-verified-retry'])
    processor = SourceVerifiedRetryIntents(queue)
    assert processor.tick(current) == 'SOURCE_VERIFIED_REQUEUED_ONE'
    assert state.work.load(key)[0].status is WorkStatus.PLANNED
    assert state.work.load(intent)[0].status is WorkStatus.VERIFIED
    assert processor.tick(current) == 'NO_INPUT'
    with state.db() as db:
        assert db.execute('SELECT COUNT(*) FROM klm_retry_history').fetchone()[0] == 1


def test_gui_retry_intent_changed_source_waits_for_review(state):
    original = records()[0]
    queue = IntakeQueue(state); queue.enqueue(original)
    key = 'klm-drive:' + original['intake_id']
    state.work.set(key, 0, WorkStatus.FAILED, 'ValueError')
    intent = 'klm-retry-intent:' + original['intake_id']
    state.work.ensure(intent, ['klm-source-verified-retry'])
    processor = SourceVerifiedRetryIntents(queue)
    def changed(pointer):
        return {**current(pointer), 'revision':'not-the-original'}
    assert processor.tick(changed) == 'SOURCE_CHANGED'
    assert state.work.load(intent)[0].status is WorkStatus.WAITING_HUMAN
    assert state.work.load(key)[0].status is WorkStatus.FAILED


def test_model_probe_unknown_or_busy_is_not_idle():
    assert not local_compute_unoccupied(lambda port:{'models':[]},['Runner.Worker'])
    assert not local_compute_unoccupied(lambda port:{'models':[{}]},[])
    assert not local_compute_unoccupied(lambda port:(_ for _ in ()).throw(OSError()),[])
    assert local_compute_unoccupied(lambda port:{'models':[]},[])


def test_actual_development_receipt_shapes_and_read_only_bridge(tmp_path):
    (tmp_path/'inbox').mkdir();r=tmp_path/'results';r.mkdir()
    bridge=SimpleNamespace(REPOSITORY='repo',READY_LABEL='ready',_gh=lambda *a:[],
        issue_task=lambda issue:{},previous_issue_attempt=lambda *a:False)
    policy=SimpleNamespace(admission=lambda issue:{'status':'ELIGIBLE'})
    (r/'issue-1-a.started').write_text('123')
    assert read_development_state(tmp_path,bridge,policy).active_or_uncertain==1
    (r/'issue-1-a.json').write_text(json.dumps({'status':'DRAFT_PR_PRESENTED','delivery_ref':'https://github.com/quest7070-dev/AI-Foundation/pull/1','source_sha256':'a'*64}))
    assert read_development_state(tmp_path,bridge,policy).idle(time.time())
    (r/'issue-1-a.json').write_text('{bad')
    assert not read_development_state(tmp_path,bridge,policy).complete
    assert list((tmp_path/'inbox').iterdir())==[]


def test_queue_bound_creates_no_orphan_work_and_claim_conflict_has_no_handler(state):
    q=IntakeQueue(state)
    with pytest.raises(RuntimeError): q.enqueue(records()[0],max_pending=0)
    with state.db() as db: assert db.execute('SELECT COUNT(*) FROM work_steps').fetchone()[0]==0
    w=worker(state)
    job=w.queue.next()['job_id']
    # Another host process claims between observations and this worker's claim.
    w.compute_idle=lambda:(w.work.claim_not_running(job,0) or True)
    assert w.tick(read_source=pytest.fail,handler=pytest.fail)=='ALREADY_CLAIMED'


def test_handler_time_bound_refuses_late_result_without_forced_model_kill(state):
    w=worker(state);clock=[100];w.clock=lambda:clock[0]
    def late(p,s,*,deadline):
        clock[0]=deadline+1
        return handler(p,s,deadline=deadline)
    assert w.tick(read_source=current,handler=late)=='FAILED'
    failure=json.loads(w.work.load('klm-drive:'+records()[0]['intake_id'])[0].result)
    assert failure['error_type']=='TimeoutError'
    assert failure['phase']=='SOURCE_POSTREAD'
    assert len(failure['source_sha256'])==64


def test_unlabelled_inbox_cells_are_not_ignored():
    first=inbox_records([['header'],['value']],owner='owner')[0]
    second=inbox_records([['header'],['value','additional input']],owner='owner')[0]
    assert first['source_revision']!=second['source_revision']


def test_unverified_source_bytes_do_not_reach_handler_and_status_is_durable(state):
    w=worker(state)
    assert w.tick(read_source=current)=='HANDLER_UNBOUND'
    item=records()[0]
    assert w.queue.status(item['intake_id'])['status']=='HANDLER_UNBOUND'
    assert w.tick(read_source=lambda p:{**current(p),'raw':b'tampered'},handler=pytest.fail)=='FAILED'
    assert w.queue.status(item['intake_id'])['status']=='FAILED'


def test_live_source_resolver_rechecks_original_cells_not_stored_row_position():
    values=[['intake_id','状態'],['stable','first']]
    pointer=inbox_records(values,owner='owner')[0]
    pointer['row_hint']=999
    calls=[]
    def read(sid,tab,area):
        calls.append((sid,tab,area));return {'values':values}
    before=read_inbox_source(pointer,read)
    assert before['revision']=='row:'+before['sha256']
    values[1][1]='updated'
    assert read_inbox_source(pointer,read)['revision']!=before['revision']
    assert calls[0][1:]==('Inbox','A1:L100')
    with pytest.raises(PermissionError): read_inbox_source({**pointer,'source_id':'foreign'},read)


def test_legacy_source_edit_is_unresolved_instead_of_wrong_row_readback():
    old=inbox_records([['header'],['old']],owner='owner')[0]
    assert read_inbox_source(old,lambda *args:{'values':[['header'],['new']]})['revision']=='ROW_MISSING_CHANGED_OR_AMBIGUOUS'

