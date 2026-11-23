"""Cheap host-owned long-term health signals for human-unverifiable aging risks."""
from dataclasses import dataclass
from pathlib import Path
import json,os,shutil,time,math,tempfile

MAX_HEALTH_EVIDENCE_BYTES = 1024 * 1024


def _finite_number(value):
    try: return type(value) in (int, float) and math.isfinite(value)
    except OverflowError: return False


def _valid_health(health):
    if not isinstance(health, LongTermHealth) or not _finite_number(health.checked_at) or health.checked_at < 0:
        return False
    if not isinstance(health.signals, tuple) or not 1 <= len(health.signals) <= 64:
        return False
    names = set()
    for signal in health.signals:
        if not isinstance(signal, LongTermSignal) or type(signal.ok) is not bool:
            return False
        if not isinstance(signal.name, str) or not 1 <= len(signal.name) <= 128 or signal.name in names:
            return False
        if not isinstance(signal.detail, str) or len(signal.detail) > 2048:
            return False
        names.add(signal.name)
    return True


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('duplicate health field')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('non-finite health evidence')

@dataclass(frozen=True)
class LongTermSignal:
    name:str; ok:bool; detail:str

@dataclass(frozen=True)
class LongTermHealth:
    checked_at:float; signals:tuple[LongTermSignal,...]
    @property
    def ok(self): return _valid_health(self) and all(x.ok is True for x in self.signals)

def _size(path):
    p=Path(path)
    try:
        if not p.exists(): return 0
        if p.is_file(): return p.stat().st_size
        return sum(x.stat().st_size for x in p.rglob('*') if x.is_file())
    except OSError:return -1

def check_long_term_health(data_dir,*,disk_warn_free_bytes=10*1024**3,storage_admission=None,llama_log_warn_bytes=256*1024**2,handoff_warn_bytes=1024**3,trace_warn_bytes=64*1024**2,push_state_warn_bytes=1024**2,clock=time.time):
    root=Path(data_dir); signals=[]
    if storage_admission is not None:
        status=storage_admission.status()
        signals.append(LongTermSignal('free-space',status.writable,status.detail))
    else:
        try:
            free=shutil.disk_usage(root if root.exists() else root.parent).free
            signals.append(LongTermSignal('free-space',free>=disk_warn_free_bytes,f'{free} bytes free'))
        except OSError: signals.append(LongTermSignal('free-space',False,'unreadable'))
    log=_size(root/'local-compute'/'llama-swap.log')
    signals.append(LongTermSignal('llama-swap-log',0<=log<llama_log_warn_bytes,f'{log} bytes'))
    handoff=_size(root/'.foundation-handoff')
    signals.append(LongTermSignal('attachment-handoff',0<=handoff<handoff_warn_bytes,f'{handoff} bytes'))
    # Observe only bounded operational metadata/log surfaces. Never inspect or retain
    # user content in health evidence; details are byte counts only.
    trace=_size(root/'trace.jsonl')
    signals.append(LongTermSignal('foundation-trace',0<=trace<trace_warn_bytes,f'{trace} bytes'))
    push=_size(root/'remote'/'push-seen.json')
    signals.append(LongTermSignal('push-dedup-state',0<=push<push_state_warn_bytes,f'{push} bytes'))
    evidence=_size(root/'long-term-health.json')
    signals.append(LongTermSignal('health-evidence',0<=evidence<1024**2,f'{evidence} bytes'))
    for name in ('guard.db-wal','work.db-wal','providers.sqlite-wal','routing.sqlite-wal','reconciliation.sqlite-wal','inference-attempts.sqlite-wal'):
        n=_size(root/name)
        signals.append(LongTermSignal('wal:'+name,0<=n<256*1024**2,f'{n} bytes'))
    return LongTermHealth(clock(),tuple(signals))

class LongTermHealthEvidenceStore:
    """Atomic single-record evidence; bounded regardless of runtime age."""
    def __init__(self,path): self.path=Path(path)
    def save(self,health):
        if not _valid_health(health): raise ValueError('invalid health observation')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        payload={"checked_at":health.checked_at,"ok":health.ok,"signals":[{"name":x.name,"ok":x.ok,"detail":x.detail} for x in health.signals]}
        raw=(json.dumps(payload,separators=(',',':'),allow_nan=False)+'\n').encode('utf-8')
        if len(raw)>MAX_HEALTH_EVIDENCE_BYTES: raise ValueError('health evidence too large')
        fd,name=tempfile.mkstemp(prefix='.'+self.path.name+'.',suffix='.tmp',dir=self.path.parent)
        tmp=Path(name)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
            os.replace(tmp,self.path)
            if self.load()!=health: raise ValueError('health evidence readback failed')
        finally: tmp.unlink(missing_ok=True)
    def load(self):
        try:
            with self.path.open('rb') as stream: raw=stream.read(MAX_HEALTH_EVIDENCE_BYTES+1)
            if len(raw)>MAX_HEALTH_EVIDENCE_BYTES:return None
            d=json.loads(raw,object_pairs_hook=_unique_fields,parse_constant=_reject_constant)
            if not isinstance(d,dict) or set(d)!={'checked_at','ok','signals'} or type(d['ok']) is not bool:return None
            if not isinstance(d['signals'],list) or not 1<=len(d['signals'])<=64:return None
            if any(not isinstance(x,dict) or set(x)!={'name','ok','detail'} for x in d['signals']):return None
            health=LongTermHealth(d['checked_at'],tuple(LongTermSignal(x['name'],x['ok'],x['detail']) for x in d['signals']))
            return health if _valid_health(health) and d['ok'] is health.ok else None
        except (OSError,ValueError,KeyError,TypeError,UnicodeError,RecursionError): return None

class LongTermHealthLoop:
    """Periodic observer. Observation is intentionally separate from cleanup."""
    def __init__(self,check,interval=3600,clock=time.time,evidence_store=None,monotonic=None,maintenance=None):
        import threading
        if not _finite_number(interval) or interval>threading.TIMEOUT_MAX:raise ValueError('invalid health interval')
        self.check=check; self.interval=max(60,interval); self.clock=clock; self.evidence_store=evidence_store
        self.monotonic=time.monotonic if monotonic is None else monotonic
        self._stop=threading.Event(); self._lock=threading.Lock(); self._tick_lock=threading.Lock()
        self._last=None;self._last_monotonic=None;self._thread=None;self._start_lock=threading.Lock()
        if maintenance is not None and not callable(maintenance):raise ValueError("invalid maintenance callback")
        self.maintenance=maintenance;self._wake=threading.Event()
    def _failure(self,name,detail):
        try: now=self.clock()
        except Exception: now=0
        if not _finite_number(now) or now<0:now=0
        return LongTermHealth(now,(LongTermSignal(name,False,detail),))
    @staticmethod
    def _with_failure(health,name,detail):
        signals=tuple(x for x in health.signals if x.name!=name)[:63]
        return LongTermHealth(health.checked_at,signals+(LongTermSignal(name,False,detail),))
    def tick(self):
        if not self._tick_lock.acquire(blocking=False):return self.latest()
        try:
            try: started=self.monotonic()
            except Exception: started=None
            try:
                result=self.check()
                if not _valid_health(result):raise ValueError('invalid health observation')
            except Exception:
                result=self._failure('health-check','check-failed')
            if not _finite_number(started):result=self._with_failure(result,'health-clock','clock-unavailable')
            if self.evidence_store is not None:
                try:self.evidence_store.save(result)
                except Exception:result=self._with_failure(result,'health-evidence','write-failed')
            with self._lock:self._last=result;self._last_monotonic=started
            return result
        finally:self._tick_lock.release()
    def latest(self):
        with self._lock:return self._last
    def trustworthy(self,*,stale_after=None,now=None):
        """Return latest evidence only while it is fresh; stale OK is never trusted."""
        if self._stop.is_set() or (self._thread is not None and not self._thread.is_alive()):return None
        with self._lock:result=self._last;observed=self._last_monotonic
        if not _valid_health(result) or not _finite_number(observed):return None
        try: wall=self.clock() if now is None else now;current=self.monotonic()
        except Exception:return None
        limit=(self.interval*2 if stale_after is None else stale_after)
        if not _finite_number(wall) or not _finite_number(current) or not _finite_number(limit) or limit<0:return None
        elapsed=current-observed
        age=wall-result.checked_at
        if age < 0 or age > limit or elapsed<0 or elapsed>limit:return None
        return result
    def ok(self,*,stale_after=None,now=None):
        result=self.trustworthy(stale_after=stale_after,now=now)
        return result is not None and result.ok
    def wake_maintenance(self):
        # An existing exact Guard decision can advance maintenance promptly.
        # No new scheduler, thread, authority or modification in health tick().
        if self.maintenance is not None:self._wake.set()
    def run(self):
        while not self._stop.is_set():
            self.tick()
            deadline=self.monotonic()+self.interval
            while not self._stop.is_set():
                self._wake.clear()
                if self.maintenance is not None:
                    try:self.maintenance()
                    except Exception:pass  # local receipt remains authoritative
                remaining=deadline-self.monotonic()
                if remaining<=0 or not self._wake.wait(remaining):break
    def start(self):
        import threading
        with self._start_lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread=threading.Thread(target=self.run,name='foundation-long-term-health',daemon=True)
                self._thread.start()
            return self._thread
    def stop(self):self._stop.set();self._wake.set()
