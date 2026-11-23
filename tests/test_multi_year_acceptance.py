import json,os,sqlite3
from pathlib import Path
from ai_foundation.productization import FoundationConfig,backup,restore
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.durable_inference import SQLiteInferenceAttemptStore
from ai_foundation.retention import RetentionService,RetentionPolicy
from ai_foundation.notification_dismissal import NotificationDismissals
from ai_foundation.task_intake import TaskIntake
from ai_foundation.orchestration import WorkStatus
from ai_foundation.long_term_health import check_long_term_health

def test_accelerated_multi_year_authority_lifecycle_restore_and_health(tmp_path):
 root=tmp_path/'live';root.mkdir();cfg=FoundationConfig(str(root.resolve()));g=SQLiteGuardStore(root/cfg.guard_db);w=SQLiteWorkStore(root/cfg.work_db);inf=SQLiteInferenceAttemptStore(root/cfg.inference_db)
 # Projected history: authority/audit is retained; terminal transient state is eligible by policy.
 with sqlite3.connect(root/cfg.guard_db) as db:
  db.executemany('INSERT INTO effects(effect_id,run_id,target,expected,status,paid_cost,updated_at) VALUES(?,?,?,?,?,?,?)',((f'e{i}',f'r{i}','t','x','VERIFIED',0,1) for i in range(5000)))
 for i in range(1000):
  inf.get_or_begin(f'i{i}','b');inf.complete(f'i{i}','ok')
 intake=TaskIntake(root/cfg.work_db);dismiss=NotificationDismissals(root/cfg.work_db)
 for i in range(500):
  r=intake.submit(f'task {i}');intake.store.set(r.job_id,0,WorkStatus.VERIFIED,'ok');dismiss.dismiss(r.job_id,'VERIFIED')
 assert intake.purge_terminal()==500
 with sqlite3.connect(root/cfg.work_db) as db:assert db.execute('select count(*) from notification_dismissals').fetchone()[0]==0
 # Advance years: terminal inference is pruned, retained Guard authority is not.
 RetentionService(root/cfg.guard_db,root/cfg.work_db,root/cfg.inference_db,RetentionPolicy(terminal_seconds=1),clock=lambda:4_102_444_800).prune()
 with sqlite3.connect(root/cfg.inference_db) as db:assert db.execute('select count(*) from inference_attempts').fetchone()[0]==0
 with sqlite3.connect(root/cfg.guard_db) as db:assert db.execute('select count(*) from effects').fetchone()[0]==5000 and db.execute('pragma quick_check').fetchone()[0]=='ok'
 # Snapshot/restore the aged authority and prove integrity/readback on a clean root.
 b=tmp_path/'backup';backup(cfg,b);restored=tmp_path/'restored';restore(b,restored)
 with sqlite3.connect(restored/cfg.guard_db) as db:assert db.execute('select count(*) from effects').fetchone()[0]==5000 and db.execute('pragma quick_check').fetchone()[0]=='ok'
 with sqlite3.connect(restored/cfg.work_db) as db:assert db.execute('pragma quick_check').fetchone()[0]=='ok'
 h=check_long_term_health(restored,disk_warn_free_bytes=1);assert h.ok
 # No synthetic unresolved work remains and bounded health state contains sizes, not user payloads.
 assert TaskIntake(restored/cfg.work_db).recent(20)==[] and 'task 499' not in repr(h)
