import sqlite3
from dataclasses import dataclass
from pathlib import Path
from .productization import platform_capabilities

@dataclass(frozen=True)
class Check:
    name:str
    ok:bool
    detail:str=''

@dataclass(frozen=True)
class PreflightReport:
    checks:tuple[Check,...]
    @property
    def ready(self): return all(c.ok for c in self.checks)

def _db_check(path):
    p=Path(path)
    if not p.exists(): return Check('database:'+p.name,True,'not-created')
    try:
        with sqlite3.connect(f'file:{p}?mode=ro',uri=True,timeout=0.25) as db: row=db.execute('pragma integrity_check').fetchone()
        return Check('database:'+p.name,row and row[0]=='ok',row[0] if row else 'no-result')
    except sqlite3.DatabaseError: return Check('database:'+p.name,False,'unreadable')

def preflight(config,native_credentials=None,required_bindings=()):
    try: config.validate(); config_ok=Check('config',True,'valid')
    except ValueError as e: return PreflightReport((Check('config',False,type(e).__name__),))
    root=Path(config.data_dir); db_names=tuple(dict.fromkeys(getattr(config,n) for n in ('guard_db','work_db','provider_db','routing_db','reconciliation_db','inference_db') if hasattr(config,n))); checks=[config_ok,*(_db_check(root/name) for name in db_names)]
    caps=platform_capabilities(); checks.append(Check('native-secret-store',caps['native_secret_store'],'supported' if caps['native_secret_store'] else 'unsupported'))
    if required_bindings:
        for binding in required_bindings:
            ok=bool(native_credentials and native_credentials.available(binding)); checks.append(Check('credential:'+binding,ok,'available' if ok else 'unavailable'))
    return PreflightReport(tuple(checks))


class CachedPreflight:
    """One-flight full integrity check for a frequently polled Operator view.

    The standalone preflight() retains its full SQLite integrity checks.
    An in-flight check never blocks a second UI request or returns cached
    'healthy' data past its freshness window. No background job or extra DB.
    """

    def __init__(self, reader, *, clock=None, interval=30.0):
        from threading import Lock
        from time import monotonic
        self._reader = reader
        self._clock = clock or monotonic
        self._interval = interval
        self._lock = Lock()
        self._cached = None
        self._until = 0.0
        self._busy = False

    def __call__(self):
        with self._lock:
            if self._cached is not None and self._clock() < self._until:
                return self._cached
            if self._busy:
                return PreflightReport((
                    Check('preflight', False, 'integrity-check-in-progress'),))
            self._busy = True
        try:
            report = self._reader()
            if not isinstance(report, PreflightReport):
                report = PreflightReport((
                    Check('preflight', False, 'integrity-check-unverified'),))
        except Exception:
            report = PreflightReport((
                Check('preflight', False, 'integrity-check-unverified'),))
        finally:
            with self._lock:
                # Cached status is a recent read-only observation, not a
                # Guard grant or a current Work/approval snapshot.
                if 'report' in locals():
                    self._cached = report
                    self._until = self._clock() + self._interval
                self._busy = False
        return report
