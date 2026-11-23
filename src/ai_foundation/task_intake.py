import re, sqlite3, time, uuid
from dataclasses import dataclass
from pathlib import Path
from .durable_work import SQLiteWorkStore

_TEXT=re.compile(r'\S')
@dataclass(frozen=True)
class TaskReceipt:
    job_id:str; text:str; created_at:int

class TaskIntake:
    """Internal durable work intake for connected producers/tests; never a Human Decision Surface composer and never executes an effect itself."""
    def __init__(self,work_db,storage_admission=None): self.path=Path(work_db); self.path.parent.mkdir(parents=True,exist_ok=True); self.storage_admission=storage_admission; self.store=SQLiteWorkStore(self.path); self._schema()
    def _schema(self):
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS task_intake(job_id TEXT PRIMARY KEY, text TEXT NOT NULL, created_at INTEGER NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS idx_task_intake_recent ON task_intake(created_at DESC,job_id DESC)')
    def submit(self,text):
        text=' '.join((text or '').split())
        if not _TEXT.search(text) or len(text)>4000: raise ValueError('invalid task')
        if self.storage_admission:self.storage_admission.require('task intake')
        job='task-'+uuid.uuid4().hex; created=int(time.time())
        self.store.create_intake(job,text,created)
        return TaskReceipt(job,text,created)
    def recent(self,limit=20):
        with sqlite3.connect(self.path) as db: rows=db.execute('SELECT job_id,text,created_at FROM task_intake ORDER BY created_at DESC,job_id DESC LIMIT ?',(limit,)).fetchall()
        return [TaskReceipt(*r) for r in rows]
    def get(self,job_id):
        with sqlite3.connect(self.path) as db: row=db.execute('SELECT job_id,text,created_at FROM task_intake WHERE job_id=?',(job_id,)).fetchone()
        if row is None: raise KeyError(job_id)
        return TaskReceipt(*row)

    def purge_terminal(self):
        """Permanently remove terminal intake/work rows; TASKS is active-work state, not history."""
        terminal=('VERIFIED','CANCELLED')
        with sqlite3.connect(self.path) as db:
            marks=','.join('?' for _ in terminal)
            # Keep large terminal sets inside SQLite instead of materializing every
            # historical job ID into Python or an unbounded IN-parameter list.
            db.execute('CREATE TEMP TABLE IF NOT EXISTS purge_jobs(job_id TEXT PRIMARY KEY) WITHOUT ROWID')
            db.execute('DELETE FROM purge_jobs')
            db.execute(f'INSERT OR IGNORE INTO purge_jobs SELECT t.job_id FROM task_intake t WHERE EXISTS (SELECT 1 FROM work_steps w WHERE w.job_id=t.job_id) AND NOT EXISTS (SELECT 1 FROM work_steps w WHERE w.job_id=t.job_id AND w.status NOT IN ({marks}))',terminal)
            count=db.execute('SELECT COUNT(*) FROM purge_jobs').fetchone()[0]
            if not count:return 0
            db.execute('DELETE FROM human_inputs WHERE job_id IN (SELECT job_id FROM purge_jobs)')
            # Dismissals are UI cache keyed by job/status, not audit authority. Once the
            # terminal job itself is purged they have no future subject to suppress.
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='notification_dismissals'").fetchone():
                db.execute('DELETE FROM notification_dismissals WHERE subject IN (SELECT job_id FROM purge_jobs)')
            db.execute('DELETE FROM work_steps WHERE job_id IN (SELECT job_id FROM purge_jobs)')
            db.execute('DELETE FROM task_intake WHERE job_id IN (SELECT job_id FROM purge_jobs)')
            return count
    def cancel(self,job_id):
        """Cancel one active intake through the TaskIntake lifecycle boundary."""
        from .orchestration import WorkStatus
        rows=self.store.load(job_id)
        if not rows: raise KeyError(job_id)
        if rows[-1].status in {WorkStatus.VERIFIED,WorkStatus.CANCELLED}: return False
        return self.store.transition(job_id,rows[-1].position,
            (WorkStatus.PLANNED,WorkStatus.RUNNING,WorkStatus.FAILED,WorkStatus.WAITING_HUMAN),
            WorkStatus.CANCELLED,'CANCELLED')

    def execute(self,job_id,runner,*,authority_resumed=False):
        receipt=self.get(job_id)
        saved=self.store.load(job_id)[0]
        if saved.status.value=='VERIFIED': return saved.result
        if saved.status.value=='WAITING_HUMAN' and not authority_resumed:
            if self.store.pending_human_input(job_id,0) is None: return 'WAITING_HUMAN'
        if not self.store.claim_not_running(job_id,0): return 'RUNNING'
        try:
            outcome=runner(receipt)
            status=getattr(outcome,'status','FAILED')
            if status=='WAITING_HUMAN':
                from .orchestration import WorkStatus
                return status if self.store.transition(job_id,0,WorkStatus.RUNNING,WorkStatus.WAITING_HUMAN,status) else 'CANCELLED'
            if status!='VERIFIED_COMPLETE':
                from .orchestration import WorkStatus
                return status if self.store.transition(job_id,0,WorkStatus.RUNNING,WorkStatus.FAILED,status) else 'CANCELLED'
            result=getattr(outcome,'result','') or ''
            from .task_result import TaskResult
            result=TaskResult(result,'VERIFIED',getattr(outcome,'route_kind',None),(f'inference:{job_id}',),getattr(outcome,'route_binding',None)).encode()
            from .orchestration import WorkStatus
            return (getattr(outcome,'result','') or '') if self.store.transition(job_id,0,WorkStatus.RUNNING,WorkStatus.VERIFIED,result) else 'CANCELLED'
        except Exception as exc:
            from .orchestration import WorkStatus
            self.store.transition(job_id,0,WorkStatus.RUNNING,WorkStatus.FAILED,type(exc).__name__)
            raise
