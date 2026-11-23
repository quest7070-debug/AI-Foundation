"""Drive pointer intake -> existing Durable Work -> development-first KLM handoff.

No Inbox writes, new model process, scheduler, task selector or inference fallback.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path
import time

from .durable_work import SQLiteWorkStore
from .orchestration import WorkStatus
from .klm_drive_input import DriveState, INBOX_ID, digest
from .knowledge_lifecycle import SourcePointer, decompose_batch

# One end-to-end KLM job budget. The worker owns the deadline; the child only enforces it.
KLM_JOB_TIMEOUT_SECONDS = 240
# Offer two 5-minute development-worker opportunities before one KLM item.
DEV_QUEUE_GRACE_SECONDS = 600


def _inbox_cells(headers,row):
    cells={k:row[i] if i<len(row) else '' for i,k in enumerate(headers)}
    cells.update({'__column_'+str(i+1):value for i,value in enumerate(row)
                  if i>=len(headers) and str(value).strip()})
    return cells


def inbox_records(values, *, owner, privacy_scope='private', resource_id=INBOX_ID):
    """Legacy headers remain unchanged. Legacy identities are content-based,
    never row-number-based; edits without a stable ID need reconciliation.
    Summaries and private row text are deliberately excluded from returned pointers.
    """
    if privacy_scope not in {'private','restricted','shareable'} or not owner:
        raise ValueError('EXPLICIT_OWNER_PRIVACY_REQUIRED')
    if not values: return ()
    headers=values[0]
    if len(headers)!=len(set(headers)): raise ValueError('DUPLICATE_HEADERS')
    out=[]; seen=set()
    for index,row in enumerate(values[1:],2):
        if not any(str(v).strip() for v in row): continue
        cells=_inbox_cells(headers,row)
        # Unlabelled populated cells are still input; do not silently lose them.
        row_hash=digest(cells)
        record_id=str(cells.get('intake_id') or 'legacy:'+row_hash)
        key=digest((resource_id,record_id,'row:'+row_hash,owner,privacy_scope))
        if key in seen: continue
        seen.add(key)
        # Source columns are claims, not admission to read arbitrary URLs/IDs.
        out.append({'intake_id':key,'source_id':resource_id,'source_revision':'row:'+row_hash,
                    'owner':owner,'privacy_scope':privacy_scope,'record_id':record_id,
                    'row_hint':index,'sheet':'Inbox','row_sha256':row_hash,
                    'identity_quality':'EXPLICIT_ID' if cells.get('intake_id') else 'LEGACY_CONTENT_ONLY',
                    'status':'STAGED','last_attempt':None,'result_ref':None})
    return tuple(out)


def read_inbox_source(pointer, read_range, *, allocated_rows=100):
    """Fresh source resolver for the existing approved Inbox, never model URLs.

    read_range(sheet_id, tab, range) is the authenticated Sheets read port.
    allocated_rows must come from independent spreadsheet metadata. No bounded
    prefix is certified complete if the actual allocated grid exceeds this cap.
    """
    if pointer['source_id']!=INBOX_ID or pointer.get('sheet')!='Inbox':
        raise PermissionError('INBOX_SOURCE_NOT_APPROVED')
    if type(allocated_rows) is not int or not 1<=allocated_rows<=1000:
        raise ValueError('INBOX_GRID_BOUND_REQUIRED')
    response=read_range(INBOX_ID,'Inbox','A1:L'+str(allocated_rows))
    values=response['values']
    candidates=inbox_records(values,owner=pointer['owner'],privacy_scope=pointer['privacy_scope'])
    matched=[r for r in candidates if r['record_id']==pointer['record_id']]
    if len(matched)!=1: return {'revision':'ROW_MISSING_CHANGED_OR_AMBIGUOUS'}
    found=matched[0];row=values[found['row_hint']-1]
    raw=json.dumps(_inbox_cells(values[0],row),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    return {'revision':found['source_revision'],'sha256':hashlib.sha256(raw).hexdigest(),'raw':raw}


def inbox_update_plan(records, existing_ids=()):
    """Pointer-only plan; no method exists to apply it to Drive."""
    return tuple({'intake_id':r['intake_id'],'operation':'NO_CHANGE' if r['intake_id'] in existing_ids else 'PROPOSE_POINTER_ONLY',
                  'source_id':r['source_id'],'source_revision':r['source_revision'],
                  'existing_row':r['row_hint'],'effect_authorized':False,
                  'reason':'READ_ONLY_EXISTING_HEADERS_PRESERVED'} for r in records)


class IntakeQueue:
    def __init__(self, state:DriveState): self.state=state; self.work=state.work

    def enqueue(self, record, *, max_pending=1000):
        required={'intake_id','source_id','source_revision','owner','privacy_scope','record_id'}
        if not required<=record.keys(): raise ValueError('INVALID_INTAKE_POINTER')
        identity=digest((record['source_id'],record['record_id'],record['source_revision'],record['owner'],record['privacy_scope']))
        if record['intake_id']!=identity: raise ValueError('INTAKE_IDENTITY_MISMATCH')
        job='klm-drive:'+identity
        # Extend existing work_steps and source pointer in ONE transaction. Job
        # claims/readback still use SQLiteWorkStore's existing public methods.
        with self.state.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM klm_drive_intake WHERE intake_id=?',(identity,)).fetchone(): return 'ALREADY_STAGED'
            if db.execute('SELECT COUNT(*) FROM klm_drive_intake').fetchone()[0]>=50000:
                raise RuntimeError('INTAKE_HISTORY_BOUND_REACHED')
            n=db.execute("SELECT COUNT(*) FROM klm_drive_intake i JOIN work_steps w ON i.job_id=w.job_id WHERE w.status IN ('PLANNED','RUNNING','FAILED','WAITING_HUMAN')").fetchone()[0]
            if n>=max_pending: raise RuntimeError('INTAKE_BOUND_REACHED')
            db.execute("INSERT INTO work_steps(job_id,position,name,status,result,updated_at) VALUES(?,0,'klm-readonly','PLANNED','',?)",
                       (job,time.time()))
            # A newer revision invalidates unstarted work; historical receipts remain.
            old=db.execute('SELECT job_id FROM klm_drive_intake WHERE source_id=? AND record_id=? AND owner=? AND privacy_scope=?',
                (record['source_id'],record['record_id'],record['owner'],record['privacy_scope'])).fetchall()
            for row in old:
                db.execute("UPDATE work_steps SET status='CANCELLED',result='SOURCE_CHANGED',updated_at=? WHERE job_id=? AND status IN ('PLANNED','FAILED')",(time.time(),row[0]))
            db.execute('INSERT INTO klm_drive_intake VALUES(?,?,?,?,?,?,?,?,?)',
                (identity,record['source_id'],record['source_revision'],record['owner'],record['privacy_scope'],record['record_id'],time.time(),job,json.dumps(record)))
        return 'STAGED'

    def next(self):
        with self.state.db() as db:
            row=db.execute("SELECT i.* FROM klm_drive_intake i JOIN work_steps w ON i.job_id=w.job_id WHERE w.position=0 AND w.status='PLANNED' ORDER BY i.created,i.intake_id LIMIT 1").fetchone()
        return dict(row) if row else None

    def backlog(self, *, now=None):
        now=time.time() if now is None else now
        with self.state.db() as db:
            row=db.execute("SELECT COUNT(*),MIN(i.created) FROM klm_drive_intake i JOIN work_steps w ON i.job_id=w.job_id WHERE w.status IN ('PLANNED','RUNNING','FAILED','WAITING_HUMAN')").fetchone()
            uncertain=db.execute("SELECT COUNT(*) FROM klm_drive_intake i JOIN work_steps w ON i.job_id=w.job_id WHERE w.status='RUNNING'").fetchone()[0]
        return {'pending':row[0],'oldest_age_s':max(0,now-row[1]) if row[1] is not None else 0,
                'uncertain_running':uncertain}

    def status(self,intake_id):
        with self.state.db() as db:
            row=db.execute('SELECT * FROM klm_drive_intake WHERE intake_id=?',(intake_id,)).fetchone()
        if row is None: raise KeyError(intake_id)
        saved=self.work.load(row['job_id'])[0]
        try: details=json.loads(saved.result) if saved.result else {}
        except ValueError: details={'reason':saved.result}
        if not isinstance(details,dict): details={}
        return {'intake_id':intake_id,'source_id':row['source_id'],'source_revision':row['source_revision'],
                'owner':row['owner'],'privacy_scope':row['privacy_scope'],
                'status':details.get('reason','STAGED') if saved.status is WorkStatus.PLANNED else saved.status.value,
                'last_attempt':details.get('last_attempt'),'result_ref':details.get('result_ref')}

    def requeue_failed(self, intake_id, *, expected_revision, expected_sha256, read_source):
        """One explicitly selected retry; preserve history and reauthenticate bytes.

        Never called by the periodic worker. Legacy exception-only failures need
        an independently obtained expected hash; they cannot attest their own input.
        """
        if (not isinstance(intake_id,str) or not re.fullmatch(r'[a-f0-9]{64}',intake_id)
                or not isinstance(expected_sha256,str) or not re.fullmatch(r'[a-f0-9]{64}',expected_sha256)):
            raise ValueError('EXACT_RETRY_IDENTITY_REQUIRED')
        with self.state.db() as db:
            item=db.execute('SELECT * FROM klm_drive_intake WHERE intake_id=?',(intake_id,)).fetchone()
        if item is None: raise KeyError(intake_id)
        if item['source_revision']!=expected_revision: raise ValueError('RETRY_REVISION_MISMATCH')
        current=read_source(json.loads(item['pointer']))
        if (current.get('revision')!=expected_revision or current.get('sha256')!=expected_sha256
                or not isinstance(current.get('raw'),bytes)
                or not 1<=len(current['raw'])<=32768
                or hashlib.sha256(current['raw']).hexdigest()!=expected_sha256):
            raise ValueError('RETRY_ORIGINAL_NOT_VERIFIED')
        with self.state.db() as db:
            db.execute('BEGIN IMMEDIATE')
            saved=db.execute('SELECT status,result FROM work_steps WHERE job_id=? AND position=0',(item['job_id'],)).fetchone()
            if saved is None or saved['status']!='FAILED': return 'NOT_FAILED'
            db.execute('''CREATE TABLE IF NOT EXISTS klm_retry_history(
                attempt_id TEXT PRIMARY KEY, intake_id TEXT NOT NULL,
                previous_result TEXT NOT NULL, source_sha256 TEXT NOT NULL, retried_at REAL NOT NULL)''')
            if db.execute('SELECT COUNT(*) FROM klm_retry_history').fetchone()[0]>=50000:
                raise RuntimeError('RETRY_HISTORY_BOUND_REACHED')
            try: failure=json.loads(saved['result'])
            except (TypeError,ValueError): failure=saved['result']
            if isinstance(failure,dict):
                # Attempt timestamps do not make the same failure a new cause.
                failure={k:failure.get(k) for k in ('error_type','phase','source_sha256')}
            attempt=digest((intake_id,expected_sha256,failure))
            if db.execute('SELECT 1 FROM klm_retry_history WHERE attempt_id=?',(attempt,)).fetchone():
                return 'REPEATED_FAILURE_REVIEW_REQUIRED'
            db.execute('INSERT INTO klm_retry_history VALUES(?,?,?,?,?)',
                       (attempt,intake_id,saved['result'],expected_sha256,time.time()))
            db.execute("UPDATE work_steps SET status='PLANNED',result=?,updated_at=? WHERE job_id=? AND position=0 AND status='FAILED'",
                       (json.dumps({'reason':'EXPLICIT_SOURCE_VERIFIED_RETRY','previous_attempt':attempt}),time.time(),item['job_id']))
        return 'REQUEUED_ONE'




class SourceVerifiedRetryIntents:
    """Finish one exact, owner-staged retry in the existing GUI KLM host.

    A GitHub Actions runner cannot safely access the GUI owner's Keychain
    refresh secret. It only stages a Durable Work intent. This owner-bound host
    re-reads the approved Inbox, verifies bytes/revision twice through the
    existing IntakeQueue.requeue_failed and never accepts source/model content
    from the intent or GitHub Issue.
    """
    PREFIX = 'klm-retry-intent:'
    STEP = 'klm-source-verified-retry'

    def __init__(self, queue):
        self.queue, self.work = queue, queue.work

    def tick(self, read_source):
        with self.queue.state.db() as db:
            uncertain = db.execute(
                "SELECT COUNT(*) FROM work_steps WHERE name=? "
                "AND job_id LIKE ? AND status='RUNNING'",
                (self.STEP, self.PREFIX+'%')).fetchone()[0]
            if uncertain:
                return 'RECONCILE_REQUIRED'
            rows = db.execute("""
                SELECT w.job_id,i.intake_id,i.source_revision,i.pointer
                FROM work_steps w JOIN klm_drive_intake i
                  ON w.job_id=? || i.intake_id
                WHERE w.position=0 AND w.name=? AND w.status='PLANNED'
                ORDER BY i.created,i.intake_id LIMIT 2
            """, (self.PREFIX,self.STEP)).fetchall()
        if not rows:
            return 'NO_INPUT'
        if len(rows) > 1:
            return 'MULTIPLE_RETRY_INTENTS_REVIEW_REQUIRED'
        row = rows[0]
        job = row['job_id']
        if not self.work.claim_not_running(job,0):
            return 'ALREADY_CLAIMED'
        try:
            pointer = json.loads(row['pointer'])
            original = read_source(pointer)
            raw = original.get('raw')
            if (original.get('revision') != row['source_revision']
                    or not isinstance(raw,bytes)
                    or not 1 <= len(raw) <= 32768
                    or hashlib.sha256(raw).hexdigest() != original.get('sha256')):
                self.work.set(job,0,WorkStatus.WAITING_HUMAN,
                              json.dumps({'reason':'SOURCE_CHANGED_REVIEW_REQUIRED'}))
                return 'SOURCE_CHANGED'
            outcome = self.queue.requeue_failed(
                row['intake_id'], expected_revision=row['source_revision'],
                expected_sha256=original['sha256'], read_source=read_source)
            if outcome == 'REQUEUED_ONE':
                self.work.set(job,0,WorkStatus.VERIFIED,
                              json.dumps({'result':'SOURCE_VERIFIED_REQUEUED_ONE',
                                          'external_writes':0}))
                return 'SOURCE_VERIFIED_REQUEUED_ONE'
            if outcome == 'REPEATED_FAILURE_REVIEW_REQUIRED':
                self.work.set(job,0,WorkStatus.WAITING_HUMAN,
                              json.dumps({'reason':'REPEATED_FAILURE_REVIEW_REQUIRED'}))
                return 'REVIEW_REQUIRED'
            self.work.set(job,0,WorkStatus.VERIFIED,
                          json.dumps({'result':'ORIGINAL_NOT_FAILED','external_writes':0}))
            return 'ORIGINAL_NOT_FAILED'
        except Exception as exc:
            self.work.set(job,0,WorkStatus.FAILED,
                          json.dumps({'reason':'SOURCE_VERIFY_FAILED',
                                      'error_type':type(exc).__name__}))
            return 'FAILED'


class LegacyRehydrateQueue:
    """Select one source-authenticated, VERIFIED legacy input lacking new features.

    The original VERIFIED Work and hash-only atoms stay unchanged. A separate
    one-shot Durable Work identity records a no-effect review attempt. Prior
    RUNNING/FAILED/CANCELLED/VERIFIED review jobs are never auto-replayed.
    """
    PREFIX = 'klm-legacy-review:'

    def __init__(self, state):
        self.state, self.work = state, state.work

    def backlog(self):
        with self.state.db() as db:
            running = db.execute(
                "SELECT COUNT(*) FROM work_steps WHERE job_id LIKE ? "
                "AND position=0 AND status='RUNNING'", (self.PREFIX + '%',)
            ).fetchone()[0]
        return {'uncertain_running': running}

    def next(self):
        with self.state.db() as db:
            present = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            required = {'klm_drive_intake', 'work_steps', 'klm_atoms',
                        'klm_atom_features'}
            if not required.issubset(present):
                return None
            row = db.execute("""
                SELECT i.*, MIN(a.source_sha256) AS original_sha256
                FROM klm_drive_intake i
                JOIN work_steps w ON w.job_id=i.job_id AND w.position=0
                JOIN klm_atoms a
                  ON a.system='gdrive' AND a.resource_id=i.source_id
                 AND a.record_id=i.record_id AND a.revision=i.source_revision
                 AND a.scope='drive-inbox' AND a.privacy=i.privacy_scope
                LEFT JOIN klm_atom_features f ON f.atom_id=a.atom_id
                WHERE w.status='VERIFIED' AND f.atom_id IS NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM work_steps l
                    WHERE l.job_id=? || i.intake_id AND l.position=0
                      AND l.status IN ('VERIFIED','FAILED','RUNNING',
                                      'CANCELLED','WAITING_HUMAN'))
                GROUP BY i.intake_id
                HAVING COUNT(DISTINCT a.source_sha256)=1
                ORDER BY i.created, i.intake_id LIMIT 1
            """, (self.PREFIX,)).fetchone()
        if row is None:
            return None
        selected = dict(row)
        selected['expected_source_sha256'] = selected.pop('original_sha256')
        selected['job_id'] = self.PREFIX + selected['intake_id']
        self.work.ensure(selected['job_id'], ['klm-legacy-source-review'])
        return selected


@dataclass(frozen=True)
class DevObservation:
    approved_pending:int
    active_or_uncertain:int
    complete:bool
    observed_at:float
    # Audited Native-only approvals are not executable by the local9B
    # fixed-task worker; still observable and do not grant any effect.
    native_only_approved:int=0
    # Explicitly approved plan-only parent Issues are not executable Work.
    non_worker_approved:int=0
    queue_fingerprint:str=''

    def queued_only_fresh(self, now):
        """Known unchanged queue, no currently executing or uncertain development."""
        return (self.complete is True and type(self.approved_pending) is int
                and self.approved_pending>0
                and type(self.active_or_uncertain) is int
                and self.active_or_uncertain==0
                and type(self.queue_fingerprint) is str
                and re.fullmatch(r'[0-9a-f]{64}',self.queue_fingerprint) is not None
                and 0<=now-self.observed_at<=15)

    def idle(self, now):
        return (self.complete and type(self.approved_pending) is int and self.approved_pending==0
                and type(self.active_or_uncertain) is int and self.active_or_uncertain==0
                and 0<=now-self.observed_at<=15)


def _exact_native_handoff_only(issue):
    """Narrow owner-authored Native canary; never a local9B executable recipe.

    A ready label is NOT enough for the local9B worker: it accepts only an
    exact finite-task contract. Reject malformed/mixed markers conservatively.
    Keep this path-specific, not a generic bypass for future approvals.
    """
    body=issue.get('body')
    if not isinstance(body,str) or len(body)>32768:
        return False
    if 'foundation-autodev-task' in body:
        return False
    markers=re.findall(r'<!-- foundation-autodev:\s*(\{[^\r\n]*\})\s*-->',body)
    if len(markers)!=1:
        return False

    def unique(pairs):
        result={}
        for k,v in pairs:
            if k in result:
                raise ValueError('DUPLICATE_NATIVE_MARKER_KEY')
            result[k]=v
        return result
    try:
        contract=json.loads(markers[0],object_pairs_hook=unique)
        path='src/ai_foundation/paseo_foundation_runtime.py'
        target=contract['native_handoff']
        if (type(contract) is not dict or set(contract)!={'paths','depends_on','native_handoff'}
                or contract['paths']!=[path] or contract['depends_on']!=[]
                or type(target) is not dict
                or set(target)!={'anchor','target','calls','acceptance_paths'}
                or target['target']!=path
                or type(target['anchor']) is not str
                or not 1<=len(target['anchor'])<=1024
                or type(target['calls']) is not list
                or not 1<=len(target['calls'])<=8
                or type(target['acceptance_paths']) is not list
                or target['acceptance_paths']!=['tests/test_paseo_signed_ingress_slot.py']):
            return False
        for call in target['calls']:
            if (type(call) is not list or len(call)!=2
                    or type(call[0]) is not str or not 1<=len(call[0])<=80
                    or type(call[1]) is not list or not 1<=len(call[1])<=8
                    or any(type(x) is not str or not 1<=len(x)<=120 for x in call[1])):
                return False
    except (ValueError,KeyError,TypeError):
        return False
    return True


def _exact_non_worker_harness_parent(issue):
    """Recognize only the owner-approved #555 *planning parent*, not child jobs.

    This cannot waive an actual finite 9B task. No general bypass for Issues
    merely claiming to be research/planning; the exact marker, issue number,
    non-executable authority text and fixed two-source scope must all match.
    """
    if issue.get("number") != 555:
        return False
    body = issue.get("body")
    if (not isinstance(body, str) or len(body) > 32768
            or re.search(r"<!--\s*foundation-autodev-task\s*:", body) is not None
            or "**EXACT_PARENT_SCOPE_APPROVED / NO CHILD EXECUTION YET.**" not in body):
        return False
    markers = re.findall(r"<!-- foundation-autodev:\s*(\{[^\r\n]*\})\s*-->", body)
    if len(markers) != 1:
        return False
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("DUPLICATE_PARENT_CONTRACT_KEY")
            out[key] = value
        return out
    try:
        contract = json.loads(markers[0], object_pairs_hook=unique)
        return (type(contract) is dict and set(contract) == {"paths", "depends_on"}
                and contract["paths"] == [
                    "src/ai_foundation/agent.py",
                    "src/ai_foundation/development_loop.py",
                ] and contract["depends_on"] == [])
    except (ValueError, TypeError):
        return False


def read_development_state(root, bridge, selection, *, now=time.time):
    """Read through the EXISTING approved-Issue policy and durable worker receipts.

    Unlike collect_ready(), this does not write its inbox or claims. A terminal
    .json receipt resolves a start only if exact matching status proves success;
    STOPPED, malformed, missing or symlinked receipts remain uncertain.
    """
    root=Path(root)
    try:
        inbox=root/'inbox'; results=root/'results'
        if root.is_symlink() or inbox.is_symlink() or results.is_symlink() or not inbox.is_dir() or not results.is_dir():
            raise ValueError('WORKER_STATE_UNAVAILABLE')
        issues=bridge._gh('issue','list','--repo',bridge.REPOSITORY,'--state','open',
            '--label',bridge.READY_LABEL,'--limit','100','--json','number,body,labels,state,updatedAt')
        if not isinstance(issues,list) or len(issues)>=100: raise ValueError('ISSUE_COVERAGE_UNPROVEN')
        pending=0
        pending_identity=[]
        native_only=0
        non_worker=0
        for issue in issues:
            if selection.admission(issue)['status']!='ELIGIBLE': continue
            if _exact_non_worker_harness_parent(issue):
                non_worker += 1
                continue
            try: bridge.issue_task(issue)
            except (ValueError,KeyError,TypeError):
                if _exact_native_handoff_only(issue):
                    # Exact Native-only canary #35 is a separate execution
                    # owner, not pending local9B finite-task compute demand.
                    # Running/uncertain jobs still block through markers,
                    # occupancy and the shared HostComputeLease.
                    native_only+=1
                    continue
                # Unknown or malformed contracts remain conservatively pending.
                pending+=1
                pending_identity.append((issue.get('number'),issue.get('updatedAt')))
                continue
            if not bridge.previous_issue_attempt(inbox,issue['number']):
                pending+=1
                pending_identity.append((issue.get('number'),issue.get('updatedAt')))
        uncertain=0
        for marker in set(results.glob('*.started'))|set(results.glob('*.claimed')):
            if marker.is_symlink() or not marker.is_file(): raise ValueError('UNTRUSTED_RECEIPT')
            name=marker.read_text().strip() if marker.suffix=='.claimed' else marker.stem+'.json'
            if Path(name).name!=name or not name.endswith('.json'): raise ValueError('UNTRUSTED_RECEIPT_ID')
            result=results/name
            if result.is_symlink(): raise ValueError('UNTRUSTED_RESULT')
            data=json.loads(result.read_text()) if result.is_file() else {}
            # Published success is still not production deployment. Inspect only
            # statuses emitted by the existing GitDraftPublisher/development host.
            proven_draft=(data.get('status')=='DRAFT_PR_PRESENTED'
                and re.fullmatch(r'https://github.com/quest7070-dev/AI-Foundation/pull/[1-9][0-9]*',str(data.get('delivery_ref','')))
                and re.fullmatch(r'[a-f0-9]{64}',str(data.get('source_sha256',''))))
            finished_without_publication=data.get('status') in {'REPAIR_BUDGET_EXHAUSTED','INVALID_PROPOSAL','NO_PROGRESS','TESTED_CHANGE'}
            if not proven_draft and not finished_without_publication:
                uncertain+=1
        # Only source-authenticated pending worker tasks count as demand.
        # A partial or malformed timestamp cannot establish queue stability.
        complete_identity=all(
            type(number) is int and number>0
            and type(updated) is str
            and re.fullmatch(r'20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z',updated)
            for number,updated in pending_identity)
        fingerprint=(hashlib.sha256(json.dumps(sorted(pending_identity),
                     separators=(',',':')).encode()).hexdigest()
                     if pending and complete_identity else '')
        return DevObservation(pending,uncertain,True,now(),native_only,non_worker,
                              fingerprint)
    except Exception:
        return DevObservation(0,0,False,now())


class IdleKlmWorker:
    """One bounded job; all three admissions are rechecked under the shared lease.

    lease is the installed HostComputeLease (not a new lock); busy_types are its
    exact exception classes. Handler must use an existing bounded local provider,
    honor deadline, and never start/evict/install/fallback to another model.
    This adapter does NOT enable a model handler or a production tick by itself.
    """
    def __init__(self, queue, *, observe_dev, lease, compute_idle, busy_types=(), clock=time.time):
        self.queue=queue; self.work=queue.work; self.observe_dev=observe_dev
        self.lease=lease; self.compute_idle=compute_idle; self.busy_types=busy_types; self.clock=clock

    def _dev_permits(self, job, observation):
        now=self.clock()
        if observation.idle(now): return True
        if not observation.queued_only_fresh(now): return False
        # Pending demand does not own the compute lease. Another newly approved
        # Issue, uncertain run or stale observation resets development priority.
        try:
            previous=json.loads(self.work.load(job)[0].result or '{}')
        except (TypeError,ValueError):
            return False
        since=previous.get('dev_wait_since')
        return (previous.get('reason') in {'WAIT_DEV_IDLE','DEFER_COMPUTE_BUSY'}
                and previous.get('dev_queue_fingerprint')==observation.queue_fingerprint
                and type(since) in (int,float)
                and DEV_QUEUE_GRACE_SECONDS<=now-since<=7*24*3600)

    def defer(self, job, reason, *, dev=None):
        # Selection is not a claim: preserve only bounded timing/identity.
        now=self.clock()
        receipt={'reason':reason,'last_attempt':now}
        if (reason in {'WAIT_DEV_IDLE','DEFER_COMPUTE_BUSY'}
                and dev is not None and dev.queued_only_fresh(now)):
            try:
                previous=json.loads(self.work.load(job)[0].result or '{}')
            except (TypeError,ValueError):
                previous={}
            since=previous.get('dev_wait_since')
            if (previous.get('reason') not in {'WAIT_DEV_IDLE','DEFER_COMPUTE_BUSY'}
                    or previous.get('dev_queue_fingerprint')!=dev.queue_fingerprint
                    or type(since) not in (int,float)
                    or not 0<=now-since<=7*24*3600):
                since=now
            receipt.update(dev_wait_since=since,
                           dev_queue_fingerprint=dev.queue_fingerprint)
        changed=self.work.transition(job,0,WorkStatus.PLANNED,WorkStatus.PLANNED,
                                     json.dumps(receipt))
        return reason if changed else 'ALREADY_CLAIMED'

    def tick(self, *, read_source, handler=None):
        if self.queue.backlog()['uncertain_running']: return 'KLM_RECONCILE_REQUIRED'
        item=self.queue.next()
        if item is None: return 'NO_INPUT'
        job=item['job_id']
        dev=self.observe_dev()
        if not self._dev_permits(job,dev): return self.defer(job,'WAIT_DEV_IDLE',dev=dev)
        if handler is None: return self.defer(job,'HANDLER_UNBOUND')
        try:
            with self.lease.hold(max_wait_s=0):
                if self.compute_idle() is not True: return self.defer(job,'DEFER_COMPUTE_BUSY',dev=dev)
                # Recheck development immediately before claiming work; do not preempt it.
                dev=self.observe_dev()
                if not self._dev_permits(job,dev): return self.defer(job,'WAIT_DEV_IDLE',dev=dev)
                if not self.work.claim_not_running(job,0): return 'ALREADY_CLAIMED'
                pointer=json.loads(item['pointer']); started=self.clock()
                phase='SOURCE_READ'
                try:
                    current=read_source(pointer)
                    if current['revision']!=item['source_revision']:
                        self.work.set(job,0,WorkStatus.CANCELLED,'SOURCE_CHANGED');return 'SOURCE_CHANGED'
                    raw=current.get('raw')
                    if not isinstance(raw,bytes) or not 1<=len(raw)<=32768 or hashlib.sha256(raw).hexdigest()!=current.get('sha256'):
                        raise ValueError('SOURCE_BYTES_NOT_VERIFIED')
                    original_sha = item.get('expected_source_sha256')
                    if original_sha is not None and (
                            not isinstance(original_sha,str)
                            or original_sha != current['sha256']):
                        self.work.set(job,0,WorkStatus.CANCELLED,'SOURCE_CHANGED')
                        return 'SOURCE_CHANGED'
                    phase='MODEL_AND_DERIVATION'
                    result=handler(pointer,current,deadline=started+KLM_JOB_TIMEOUT_SECONDS)
                    # Refuse to finalize a stale source even if inference succeeded.
                    phase='SOURCE_POSTREAD'
                    fresh=read_source(pointer)
                    if fresh['revision']!=current['revision'] or fresh['sha256']!=current['sha256']:
                        self.work.set(job,0,WorkStatus.CANCELLED,'SOURCE_CHANGED');return 'SOURCE_CHANGED'
                    if self.clock()-started>KLM_JOB_TIMEOUT_SECONDS: raise TimeoutError('KLM_TIME_BOUND_EXCEEDED')
                    if not isinstance(result,dict) or result.get('execution_authority') is not False or not result.get('result_ref'):
                        raise ValueError('NO_EFFECT_RECEIPT_REQUIRED')
                    # Persist only bounded hashes/ref, never raw or semantic text.
                    ref=result['result_ref']
                    if not isinstance(ref,str) or len(ref)>256: raise ValueError('BOUNDED_RESULT_REF_REQUIRED')
                    phase='FINALIZE'
                    receipt={'result_ref':ref,'source_revision':current['revision'],
                             'source_sha256':current['sha256'],'last_attempt':started,'execution_authority':False}
                    self.work.set(job,0,WorkStatus.VERIFIED,json.dumps(receipt))
                    return 'READ_ONLY_VERIFIED'
                except Exception as exc:
                    # Fixed categories only; exception messages may contain secrets.
                    self.work.set(job,0,WorkStatus.FAILED,json.dumps({
                        'error_type':type(exc).__name__, 'phase':phase,
                        'reason_code':'CANDIDATE_WINDOW_EXCEEDED'
                        if str(exc)=='CANDIDATE_WINDOW_EXCEEDED' else 'UNCLASSIFIED',
                        'last_attempt':started, 'source_sha256':current.get('sha256')
                        if phase!='SOURCE_READ' else None}))
                    return 'FAILED'
        except self.busy_types:
            return self.defer(job,'DEFER_COMPUTE_BUSY',dev=dev)


def klm_proposals(pointer, current, proposals):
    """Reuse PR #279 pure semantic core; caller owns authenticated source fetch.

    Returns source-bound proposals, never an authenticated HumanModel decision.
    No LLM or Drive write is hidden in this function.
    """
    scope = ('drive-public-research'
             if pointer['source_id'] == 'llmperks-owner-research'
             else 'drive-inbox')
    source=SourcePointer('gdrive',pointer['source_id'],pointer['record_id'],
        pointer['source_revision'],scope,pointer['privacy_scope'])
    return decompose_batch(source,current['raw'],source_sha256=current['sha256'],proposals=proposals)

