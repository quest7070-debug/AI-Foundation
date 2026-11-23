from dataclasses import dataclass
from .orchestration import WorkStatus

@dataclass(frozen=True)
class HumanInputResult:
    ok: bool
    subject: str
    status: str

class HumanInputService:
    """Durable input boundary. Records human data and resumes only the addressed waiting work."""
    def __init__(self, store, resume=None):
        self.store=store
        self.resume=resume

    def respond(self, subject, response):
        try:
            job_id,pos=subject.rsplit(':',1); pos=int(pos)
        except (ValueError,AttributeError):
            return HumanInputResult(False,subject,'INVALID')
        rows=self.store.load(job_id)
        if pos < 0 or pos >= len(rows): return HumanInputResult(False,subject,'NOT_FOUND')
        if rows[pos].status is not WorkStatus.WAITING_HUMAN: return HumanInputResult(False,subject,'NOT_WAITING')
        pending=self.store.pending_human_input(job_id,pos)
        if pending is not None and not self.store.human_input_context_valid(job_id,pos):
            return HumanInputResult(False,subject,'CONTEXT_CHANGED')
        if pending is None:
            self.store.submit_human_input(job_id,pos,response)
        elif pending != response:
            # A committed answer may be awaiting recovery after a failed resume.
            # Never replace it with a later UI submission: that would detach the
            # answer from the waiting context that originally accepted it.
            return HumanInputResult(False,subject,'INPUT_ALREADY_RECORDED')
        if self.resume is None: return HumanInputResult(True,subject,'INPUT_RECORDED')
        try:
            status=self.resume(job_id,pos)
        except Exception:
            return HumanInputResult(True,subject,'INPUT_RECORDED_RESUME_FAILED')
        return HumanInputResult(True,subject,str(getattr(status,'value',status)))
