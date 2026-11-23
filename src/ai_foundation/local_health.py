import sqlite3,time
from pathlib import Path

class LocalFailureCooldown:
    """Bounded local-model health feedback, never inventory or authority.

    Persistent mode uses SQLite because Operator and Hatchet worker are independent
    writers. Each binding is updated transactionally, so concurrent failures cannot
    erase unrelated cooldown entries through whole-file replacement.
    """
    def __init__(self, ttl=60.0, clock=time.time, path=None):
        # ttl/clock and the persisted expires value are legacy storage/API fields.
        # They schedule no authority transition; only success(binding) clears failure.
        self.ttl=float(ttl);self.clock=clock;self.path=Path(path) if path else None;self._until={}
        if self.path:self.path.parent.mkdir(parents=True,exist_ok=True);self._init_db()
    def _db(self):return sqlite3.connect(self.path,timeout=5)
    def _init_db(self):
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS cooldown(binding TEXT PRIMARY KEY, expires REAL NOT NULL)')
        try:self.path.chmod(0o600)
        except OSError:pass
    def fail(self,binding):
        if not binding:return
        expiry=self.clock()+self.ttl
        if self.path:
            with self._db() as db:db.execute('INSERT INTO cooldown(binding,expires) VALUES(?,?) ON CONFLICT(binding) DO UPDATE SET expires=excluded.expires',(binding,expiry))
        else:self._until[binding]=expiry
    def success(self,binding):
        if self.path:
            with self._db() as db:db.execute('DELETE FROM cooldown WHERE binding=?',(binding,))
        else:self._until.pop(binding,None)
    def excluded(self):
        # A local execution failure is real negative evidence. Elapsed wall-clock time
        # may schedule a retry elsewhere, but must not silently turn that failure into
        # recovered capacity. Only an actual successful execution clears exclusion.
        if self.path:
            with self._db() as db:
                return frozenset(r[0] for r in db.execute('SELECT binding FROM cooldown WHERE expires>=0'))
        return frozenset(self._until)
