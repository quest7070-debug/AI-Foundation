from dataclasses import dataclass
import json,sqlite3,time
from pathlib import Path
@dataclass(frozen=True)
class RouteSnapshot:
 function:str; primary:str|None; standby:tuple[str,...]; optimized_at:float
class SQLiteRoutingPolicy:
 def __init__(self,path,storage_admission=None):
  self.path=Path(path);self.storage_admission=storage_admission;self.path.parent.mkdir(parents=True,exist_ok=True)
  # Schema migration is a cross-process mutation too. Serialize it so two fresh
  # SettingsService processes cannot both observe a missing column then ALTER it.
  d=sqlite3.connect(self.path,timeout=5); d.execute('PRAGMA busy_timeout=5000')
  try:
   d.execute('BEGIN EXCLUSIVE')
   d.execute('CREATE TABLE IF NOT EXISTS routes(function TEXT PRIMARY KEY, ordered_bindings TEXT NOT NULL, optimized_at REAL NOT NULL)')
   cols={r[1] for r in d.execute('PRAGMA table_info(route_runtime)')}
   if cols and 'function' not in cols:d.execute('DROP TABLE route_runtime')
   d.execute('CREATE TABLE IF NOT EXISTS route_runtime(function TEXT NOT NULL, binding TEXT NOT NULL, successes INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0, latency_ms REAL, updated_at REAL NOT NULL, last_success_at REAL, last_failure_at REAL, consecutive_failures INTEGER NOT NULL DEFAULT 0, success_latency_ms REAL, PRIMARY KEY(function,binding))')
   rcols={r[1] for r in d.execute('PRAGMA table_info(route_runtime)')}
   if 'last_success_at' not in rcols:d.execute('ALTER TABLE route_runtime ADD COLUMN last_success_at REAL')
   if 'last_failure_at' not in rcols:d.execute('ALTER TABLE route_runtime ADD COLUMN last_failure_at REAL')
   if 'consecutive_failures' not in rcols:d.execute('ALTER TABLE route_runtime ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0')
   if 'success_latency_ms' not in rcols:
    d.execute('ALTER TABLE route_runtime ADD COLUMN success_latency_ms REAL')
    # Existing aggregate latency mixed successes and failures, so it cannot be
    # truthfully reclassified as successful-completion evidence. Seed only rows
    # whose history contains no failures; mixed rows relearn on their next success.
    d.execute('UPDATE route_runtime SET success_latency_ms=latency_ms WHERE successes>0 AND failures=0')
   d.execute('CREATE TABLE IF NOT EXISTS route_phase_runtime(function TEXT NOT NULL, phase TEXT NOT NULL, binding TEXT NOT NULL, successes INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0, success_latency_ms REAL, updated_at REAL NOT NULL, last_failure_at REAL, consecutive_failures INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(function,phase,binding))')
   cols={r[1] for r in d.execute('PRAGMA table_info(routes)')}
   d.commit()
  finally:d.close()
 def optimize(self,function,candidates,preferences=None):
  if self.storage_admission:self.storage_admission.require('routing policy')
  eligible=[c for c in candidates if c.get('health')=='ONLINE' and c.get('binding')]
  # PAID ordering here is defensive only. SettingsService excludes PAID inference
  # until authoritative per-request monetary accounting is connected.
  def score(c):
   q=min(x for x in (c.get('short_remaining'),c.get('long_remaining')) if x is not None) if any(x is not None for x in (c.get('short_remaining'),c.get('long_remaining'))) else -1
   paid=1 if c.get('tier')=='PAID' else 0
   # Prefer a function-native execution protocol over a general chat model that
   # merely exposes the same capability. This is reliability topology, not a
   # provider-name preference; new native SEARCH adapters inherit it automatically.
   native=0 if function=='SEARCH' and c.get('protocol') in {'tavily-search','exa-search'} else (1 if function=='SEARCH' else 0)
   local=1 if c.get('kind')=='LOCAL' else 0
   return (paid,native,local,-q,c['binding'])
  ordered=[c['binding'] for c in sorted(eligible,key=score)]; now=time.time()
  with sqlite3.connect(self.path) as d:d.execute('INSERT INTO routes(function,ordered_bindings,optimized_at) VALUES(?,?,?) ON CONFLICT(function) DO UPDATE SET ordered_bindings=excluded.ordered_bindings,optimized_at=excluded.optimized_at',(function,json.dumps(ordered),now))
  return self.get(function)
 def get(self,function):
  with sqlite3.connect(self.path) as d:r=d.execute('SELECT ordered_bindings,optimized_at FROM routes WHERE function=?',(function,)).fetchone()
  if not r:return RouteSnapshot(function,None,(),0)
  try:
   x=json.loads(r[0])
   if not isinstance(x,list) or any(not isinstance(v,str) or not v for v in x):raise ValueError('invalid route bindings')
  except (json.JSONDecodeError,TypeError,ValueError):
   # Derived route policy is reconstructible. A malformed historical row must
   # fail this function closed, not crash the whole Operator or invent capacity.
   return RouteSnapshot(function,None,(),r[1])
  return RouteSnapshot(function,x[0] if x else None,tuple(x[1:]),r[1])
 def preferences(self,function):
  return {}

 def set_preferences(self,function,**values):
  if values:
   raise ValueError('no active routing preferences')
  return self.get(function)

 def retain_functions(self,functions):
  if self.storage_admission:self.storage_admission.require('routing policy')
  keep=tuple(functions)
  with sqlite3.connect(self.path) as d:
   if keep:
    marks=','.join('?' for _ in keep);d.execute(f'DELETE FROM routes WHERE function NOT IN ({marks})',keep)
   else:d.execute('DELETE FROM routes')
 def record_runtime(self,function,binding,success,latency_ms,now=None):
  if not binding:return
  now=time.time() if now is None else float(now); latency=max(0.0,float(latency_ms))
  with sqlite3.connect(self.path) as d:
   row=d.execute('SELECT successes,failures,latency_ms,consecutive_failures,success_latency_ms FROM route_runtime WHERE function=? AND binding=?',(function,binding)).fetchone()
   if row:
    successes,failures,old,streak,success_old=row; smoothed=latency if old is None else (0.7*float(old)+0.3*latency); success_smoothed=(latency if success_old is None else (0.7*float(success_old)+0.3*latency)) if success else success_old
    d.execute('UPDATE route_runtime SET successes=?,failures=?,latency_ms=?,updated_at=?,last_success_at=CASE WHEN ? THEN ? ELSE last_success_at END,last_failure_at=CASE WHEN ? THEN last_failure_at ELSE ? END,consecutive_failures=?,success_latency_ms=? WHERE function=? AND binding=?',(successes+(1 if success else 0),failures+(0 if success else 1),smoothed,now,success,now,success,now,0 if success else streak+1,success_smoothed,function,binding))
   else:d.execute('INSERT INTO route_runtime(function,binding,successes,failures,latency_ms,updated_at,last_success_at,last_failure_at,consecutive_failures,success_latency_ms) VALUES(?,?,?,?,?,?,?,?,?,?)',(function,binding,1 if success else 0,0 if success else 1,latency,now,now if success else None,None if success else now,0 if success else 1,latency if success else None))
 def record_phase_runtime(self,function,phase,binding,success,latency_ms,now=None):
  if not binding:return
  now=time.time() if now is None else float(now);latency=max(0.0,float(latency_ms));phase=str(phase).upper()
  with sqlite3.connect(self.path) as d:
   row=d.execute('SELECT successes,failures,success_latency_ms,consecutive_failures FROM route_phase_runtime WHERE function=? AND phase=? AND binding=?',(function,phase,binding)).fetchone()
   if row:
    successes,failures,old,streak=row;success_smoothed=(latency if old is None else .7*float(old)+.3*latency) if success else old
    d.execute('UPDATE route_phase_runtime SET successes=?,failures=?,success_latency_ms=?,updated_at=?,last_failure_at=CASE WHEN ? THEN last_failure_at ELSE ? END,consecutive_failures=? WHERE function=? AND phase=? AND binding=?',(successes+(1 if success else 0),failures+(0 if success else 1),success_smoothed,now,success,now,0 if success else streak+1,function,phase,binding))
   else:d.execute('INSERT INTO route_phase_runtime(function,phase,binding,successes,failures,success_latency_ms,updated_at,last_failure_at,consecutive_failures) VALUES(?,?,?,?,?,?,?,?,?)',(function,phase,binding,1 if success else 0,0 if success else 1,latency if success else None,now,None if success else now,0 if success else 1))
 def phase_runtime(self,binding,phase,function='CHAT'):
  with sqlite3.connect(self.path) as d:r=d.execute('SELECT successes,failures,success_latency_ms,updated_at,last_failure_at,consecutive_failures FROM route_phase_runtime WHERE function=? AND phase=? AND binding=?',(function,str(phase).upper(),binding)).fetchone()
  return None if not r else {'successes':r[0],'failures':r[1],'success_latency_ms':r[2],'updated_at':r[3],'last_failure_at':r[4],'consecutive_failures':r[5]}
 def runtime(self,binding,function='CHAT'):
  with sqlite3.connect(self.path) as d:r=d.execute('SELECT successes,failures,latency_ms,updated_at,success_latency_ms FROM route_runtime WHERE function=? AND binding=?',(function,binding)).fetchone()
  return None if not r else {'successes':r[0],'failures':r[1],'latency_ms':r[2],'updated_at':r[3],'success_latency_ms':r[4]}
 def _quota_eligible(self,x,now):
  q=[v for v in (x.get('short_remaining'),x.get('long_remaining')) if v is not None]
  # Quota evidence is observational. A fresh near-empty observation suppresses
  # execution, but elapsed reset text must not silently turn stale low quota into
  # invented recovered capacity. Provider recovery/probes own that transition.
  return not q or min(q)>3
 def choose(self,function,states,phase=None):
  r=self.get(function);state={x['binding']:x for x in states};now=time.time();order=((r.primary,) if r.primary else ())+r.standby
  eligible=[b for b in order if (b in state and state[b].get('health')=='ONLINE' and self._quota_eligible(state[b],now))]
  if not eligible:return None
  marks=','.join('?' for _ in eligible)
  with sqlite3.connect(self.path) as d: rows={b:(s,f,l,u,ls,lf,cf,sl) for b,s,f,l,u,ls,lf,cf,sl in d.execute(f'SELECT binding,successes,failures,latency_ms,updated_at,last_success_at,last_failure_at,consecutive_failures,success_latency_ms FROM route_runtime WHERE function=? AND binding IN ({marks})',(function,*eligible))}
  # Keep policy order as the deterministic tie-breaker. Runtime history changes execution only.
  def quota_key(b):
   # Quota size means the provider-reported remaining capacity: the smaller of
   # the short and long windows, the same measure optimize() ranks by. Routes
   # with an observed quota are consumed largest-first so scarce pools survive;
   # routes whose quota is unobserved (including local compute) keep competing
   # on measured execution evidence below.
   x=state[b]; q=[v for v in (x.get('short_remaining'),x.get('long_remaining')) if v is not None]
   if not q:return (1,0.0)
   return (0,-float(min(q)))
  def score(b):
   i=order.index(b); row=rows.get(b); qg,nq=quota_key(b)
   if not row:return (1,qg,nq,0,float('inf'),i)
   success,fail,latency,updated,last_success,last_failure,streak,success_latency=row; total=success+fail; failure_rate=(fail/total) if total else 0
   # A recent failed attempt is stronger evidence than lifetime aggregates. Keep
   # it out briefly, then allow deterministic recovery/re-probe without rewriting policy.
   cooldown=min(3600.0,60.0*(2**max(0,streak-1)))
   recent_failure=bool(last_failure and (not last_success or last_failure>last_success) and now-last_failure<cooldown)
   # Among currently usable routes, measured completion latency is the primary
   # service-quality signal; lifetime failure rate is a stability tie-breaker.
   # Provider/model identity is deliberately absent from this score.
   # A recent failure (a timeout is recorded as one) still yields first: quota
   # ordering applies only among routes that are not cooling down.
   return (1 if recent_failure else 0,qg,nq,float(success_latency if success_latency is not None else 1e12),failure_rate,i)
  # Do not manufacture traffic for exploration or stale sampling. Provider
  # recovery/health probing owns discovery of recovered capacity; real requests
  # contribute runtime evidence only for routes they actually execute. An
  # unobserved route therefore follows persisted policy order, while observed
  # successful routes may be compared by real completion evidence below.
  # Agent request phase is observation metadata only. Initial and tool-followup
  # calls share the same CHAT route policy; phase-specific selection would create
  # a second routing policy for the same capability and amplify sparse E2E evidence.
  return min(eligible,key=score)
