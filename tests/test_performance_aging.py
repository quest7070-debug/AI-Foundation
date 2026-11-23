import sqlite3,time
from ai_foundation.operator import snapshot
from ai_foundation.productization import FoundationConfig
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.settings_service import SettingsService
from ai_foundation.provider_onboarding import ProbeResult
class Secrets:
 def save(self,*a):pass
 def load(self,*a):return 'x'
 def delete(self,*a):return True
 def available(self,*a):return True
class Probe:
 def probe(self,s,h=None):return ProbeResult(h or 'GROQ','ONLINE',80,'1m',70,'1d')

def test_aged_core_read_paths_have_explicit_latency_ceiling(tmp_path):
 cfg=FoundationConfig(str(tmp_path.resolve()));g=SQLiteGuardStore(tmp_path/cfg.guard_db);w=SQLiteWorkStore(tmp_path/cfg.work_db)
 with sqlite3.connect(tmp_path/cfg.guard_db) as db:
  db.executemany('INSERT INTO effects(effect_id,run_id,target,expected,status,paid_cost,updated_at) VALUES(?,?,?,?,?,?,?)',((f'e{i}',f'r{i}','t','x','VERIFIED',0,i) for i in range(20000)))
 with sqlite3.connect(tmp_path/cfg.work_db) as db:
  db.executemany('INSERT INTO work_steps(job_id,position,name,status,result,updated_at) VALUES(?,?,?,?,?,?)',((f'j{i}',0,'x','VERIFIED','',i) for i in range(20000)))
 # Warm filesystem/page cache once; threshold is deliberately broad and catches accidental full Python materialization/N+1 regressions, not micro-performance.
 snapshot(cfg);t=time.perf_counter();s=snapshot(cfg);elapsed=time.perf_counter()-t
 assert s.ready and elapsed<1.0
 svc=SettingsService(tmp_path/'settings',Probe(),Secrets());t=time.perf_counter();svc.optimize_all_routes();assert time.perf_counter()-t<0.5
