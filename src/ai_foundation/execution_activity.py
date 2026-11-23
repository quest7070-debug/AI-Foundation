from dataclasses import dataclass
import threading,time

@dataclass(frozen=True)
class ExecutionActivity:
    job_id:str; function:str; binding:str; kind:str; provider:str; started_at:float

class ExecutionActivityRegistry:
    """Read-only operator observation of currently selected compute. Never grants authority."""
    def __init__(self): self._lock=threading.RLock(); self._rows={}
    def start(self,job_id,function,binding,kind,provider):
        with self._lock:self._rows[job_id]=ExecutionActivity(job_id,function,binding,kind,provider,time.time())
    def finish(self,job_id):
        with self._lock:self._rows.pop(job_id,None)
    def current(self):
        with self._lock:return tuple(self._rows.values())
    def active(self,job_id,function,provider):
        self.start(job_id,function,'capability:'+function.lower(),'CAPABILITY',provider)
    def inactive(self,job_id):
        self.finish(job_id)
