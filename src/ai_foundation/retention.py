"""Bounded, fail-closed retention for terminal Foundation history.

Only terminal/consumed/expired records are eligible. Active, unresolved and
uncertain authority is deliberately never removed by this maintenance path.
"""
from dataclasses import dataclass
import sqlite3,time

@dataclass(frozen=True)
class RetentionPolicy:
    terminal_seconds:int=90*86400
    consumed_input_seconds:int=30*86400
    expired_claim_seconds:int=7*86400

class RetentionService:
    def __init__(self,guard_db,work_db,inference_db,policy=RetentionPolicy(),clock=time.time):
        self.guard_db=str(guard_db); self.work_db=str(work_db); self.inference_db=str(inference_db)
        self.policy=policy; self.clock=clock; self._last_now=clock()
    @staticmethod
    def _db(path):
        db=sqlite3.connect(path,timeout=5); db.execute('PRAGMA busy_timeout=5000'); return db
    def prune(self):
        now=self.clock()
        # Destructive age decisions fail closed after a backward wall-clock step.
        # This avoids treating a corrected clock as trustworthy retention time.
        if self._last_now is not None and now < self._last_now:
            self._last_now=now
            return {'effect_claims':0,'target_claims':0,'startup_leases':0,'human_inputs':0,'inference_attempts':0}
        self._last_now=now; out={}
        with self._db(self.guard_db) as db:
            claim_cut=now-self.policy.expired_claim_seconds
            out['effect_claims']=db.execute('DELETE FROM effect_claims WHERE expires<?',(claim_cut,)).rowcount
            out['target_claims']=db.execute('DELETE FROM target_claims WHERE expires<?',(claim_cut,)).rowcount
            out['startup_leases']=db.execute('DELETE FROM startup_leases WHERE expires<?',(claim_cut,)).rowcount
            # Effects/approvals/cancellations are authority/audit records. Do not
            # prune them until their cross-table/run retention contract is explicit.
        with self._db(self.work_db) as db:
            cut=now-self.policy.consumed_input_seconds
            out['human_inputs']=db.execute('DELETE FROM human_inputs WHERE consumed_at IS NOT NULL AND consumed_at<?',(cut,)).rowcount
        with self._db(self.inference_db) as db:
            cut=now-self.policy.terminal_seconds
            out['inference_attempts']=db.execute("DELETE FROM inference_attempts WHERE status IN ('VERIFIED','FAILED') AND updated_at<?",(cut,)).rowcount
            # UNCERTAIN/DISPATCHING are reconciliation evidence and never age out.
        return out

class RetentionLoop:
    """Bounded host-owned maintenance loop; destructive policy stays inside RetentionService."""
    def __init__(self,service,interval=86400):
        import threading
        self.service=service;self.interval=max(3600,int(interval));self._stop=threading.Event();self._lock=threading.Lock();self._last=None
    def tick(self):
        if not self._lock.acquire(blocking=False):return None
        try:self._last=self.service.prune();return self._last
        finally:self._lock.release()
    def run(self):
        self.tick()
        while not self._stop.wait(self.interval):self.tick()
    def start(self):
        import threading
        t=threading.Thread(target=self.run,name='foundation-retention',daemon=True);t.start();return t
    def stop(self):self._stop.set()
