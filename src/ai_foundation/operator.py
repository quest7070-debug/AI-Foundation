from dataclasses import dataclass
from pathlib import Path
import json,sqlite3,time
from threading import Lock
from time import monotonic
from .preflight import preflight
from .productization import SCHEMA_VERSION

@dataclass(frozen=True)
class OperatorSnapshot:
    version:int; ready:bool; checks:tuple[dict,...]; effects:dict[str,int]; waiting_human:int; work:dict[str,int]; trace_present:bool; attention:tuple[dict,...]; services:tuple[dict,...]=(); backup:dict|None=None; update:dict|None=None
    def as_dict(self): return {'version':self.version,'ready':self.ready,'checks':list(self.checks),'effects':self.effects,'waiting_human':self.waiting_human,'work':self.work,'trace_present':self.trace_present,'attention':list(self.attention),'services':list(self.services),'backup':self.backup,'update':self.update}

class OperatorReadError(RuntimeError): pass
def _rows(path,query):
    p=Path(path)
    if not p.exists(): return []
    try:
        with sqlite3.connect(f'file:{p}?mode=ro',uri=True,timeout=0.25) as db:return db.execute(query).fetchall()
    except (sqlite3.DatabaseError,sqlite3.OperationalError) as exc:
        raise OperatorReadError(p.name) from exc

class CachedServiceProbe:
    """One-flight, bounded-lifetime service observation; never an approval.

    A contending caller sees UNKNOWN, not DOWN. The only evidence for DOWN
    is an actual False return from the installed owner probe. Bad results,
    callbacks that raise, and an in-flight observation remain unverified.
    No background job, model call, process restart or private error text.
    """
    def __init__(self, callback, *, clock=monotonic, interval=10.0):
        if not callable(callback) or interval <= 0:
            raise ValueError("invalid service probe")
        self.callback, self.clock, self.interval = callback, clock, interval
        self.lock = Lock()
        self.busy = False
        self.cached = None
        self.expiry = 0.0

    def observation(self):
        with self.lock:
            now = self.clock()
            if self.cached is not None and now < self.expiry:
                return dict(self.cached)
            if self.busy:
                return {"ok": None, "detail": "probe-in-progress"}
            self.busy = True
        result = {"ok": None, "detail": "probe-unverified"}
        try:
            observed = self.callback()
            if type(observed) is bool:
                result = {"ok": observed,
                          "detail": "ready" if observed else "unavailable"}
        except Exception:
            result = {"ok": None, "detail": "probe-failed"}
        finally:
            with self.lock:
                self.cached = result
                self.expiry = self.clock() + self.interval
                self.busy = False
        return dict(result)

    def __call__(self):
        return self.observation()["ok"]


def _service(name, probe):
    if type(probe) is CachedServiceProbe:
        return {"name": name, **probe.observation()}
    try:
        observed = probe()
    except Exception:
        return {"name": name, "ok": None, "detail": "probe-failed"}
    if type(observed) is not bool:
        return {"name": name, "ok": None, "detail": "probe-unverified"}
    return {"name": name, "ok": observed,
            "detail": "ready" if observed else "unavailable"}

def _backup_status(path):
    if not path:return None
    p=Path(path); manifest=p/'manifest.json'
    if not manifest.exists():return {'present':False,'age_seconds':None,'schema_version':None}
    try:
        row=json.loads(manifest.read_text(encoding='utf-8')); age=max(0,int(time.time()-manifest.stat().st_mtime)); return {'present':True,'age_seconds':age,'schema_version':row.get('schema_version')}
    except (OSError,ValueError,json.JSONDecodeError):return {'present':False,'age_seconds':None,'schema_version':None}
def _update_status(config,stage_path):
    from .migration import read_update_journal
    journal=read_update_journal(config)
    p=Path(stage_path) if stage_path else None
    staged=bool(p and p.exists())
    try: entries=sum(1 for _ in p.iterdir()) if staged else 0
    except OSError: staged=False;entries=0
    return {'staged':staged,'entries':entries,'transaction':journal.get('status') if journal else None,'journal':bool(journal)}

def snapshot(config,native_credentials=None,required_bindings=(),service_probes=None,backup_dir=None,update_stage=None,*,preflight_report=None):
    # The Operator browser reuses one recent full integrity observation.
    # Standalone snapshots continue checking all DBs on demand.
    report=(preflight_report if preflight_report is not None
            else preflight(config,native_credentials,required_bindings))
    root=Path(config.data_dir)
    effects={str(k):int(v) for k,v in _rows(root/config.guard_db,'SELECT status,COUNT(*) FROM effects GROUP BY status')} if (root/config.guard_db).exists() else {}
    work={str(k):int(v) for k,v in _rows(root/config.work_db,'SELECT status,COUNT(*) FROM work_steps GROUP BY status')} if (root/config.work_db).exists() else {}; attention=[]
    for eid,run,target,status,updated_at in _rows(root/config.guard_db,"SELECT effect_id,run_id,target,status,updated_at FROM effects WHERE status IN ('UNCERTAIN','FAILED') ORDER BY updated_at DESC,effect_id LIMIT 100"):attention.append({'kind':'effect','id':eid,'run_id':run,'target':target,'status':status,'updated_at':updated_at})
    if (root/config.guard_db).exists():
        has_requests=bool(_rows(root/config.guard_db,"SELECT name FROM sqlite_master WHERE type='table' AND name='approval_requests'"))
        if has_requests:
            from .store import approval_request_ref
            request_cols={x[1] for x in _rows(root/config.guard_db,'PRAGMA table_info(approval_requests)')}
            # An old Guard schema is observable but not yet actionable; startup
            # migrations must establish a revision-bound request first.
            if 'request_nonce' in request_cols:
                bound = {'canon_revision','effect_id'} <= request_cols
                columns = ('run_id,action,target,updated_at,request_nonce,canon_revision,effect_id'
                           if bound else 'run_id,action,target,updated_at,request_nonce')
                query=('SELECT '+columns+' FROM approval_requests '
                       'ORDER BY updated_at DESC,run_id LIMIT 100')
                for row in _rows(root/config.guard_db,query):
                    run,action,target,updated_at,nonce = row[:5]
                    canon_revision,effect_id = row[5:] if bound else ('','')
                    ref=(approval_request_ref(run,action,target,nonce,canon_revision,effect_id)
                         if nonce and canon_revision and effect_id else '')
                    attention.append({'kind':'approval','id':run,'run_id':run,
                        'action':action,'target':target,'approval_ref':ref,
                        'status':'WAITING_HUMAN','updated_at':updated_at})
            else:
                for run,action,target,updated_at in _rows(root/config.guard_db,
                    'SELECT run_id,action,target,updated_at FROM approval_requests ORDER BY updated_at DESC,run_id LIMIT 100'):
                    attention.append({'kind':'approval','id':run,'run_id':run,
                        'action':action,'target':target,'approval_ref':'',
                        'status':'WAITING_HUMAN','updated_at':updated_at})
    for job,pos,name,status,updated_at in _rows(root/config.work_db,"SELECT job_id,position,name,status,updated_at FROM work_steps WHERE status IN ('WAITING_HUMAN','FAILED') ORDER BY updated_at DESC,job_id,position LIMIT 100"):
        row={'kind':'work','id':f'{job}:{pos}','job_id':job,'step':name,'status':status,'updated_at':updated_at}
        attention.append(row)
    checks=tuple({'name':c.name,'ok':c.ok,'detail':c.detail} for c in report.checks); services=tuple(_service(n,p) for n,p in (service_probes or {}).items())
    waiting_human=sum(1 for x in attention if x.get('status')=='WAITING_HUMAN')
    return OperatorSnapshot(SCHEMA_VERSION,report.ready,checks,effects,waiting_human,work,(root/config.trace_file).exists(),tuple(attention),services,_backup_status(backup_dir),_update_status(config,update_stage))
def render_json(value):return json.dumps(value.as_dict(),ensure_ascii=False,indent=2)+'\n'
