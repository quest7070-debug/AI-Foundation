from pathlib import Path
from ai_foundation.core import CanonContract,TaskPlan
from ai_foundation.durable_work import DurableWorkRunner,SQLiteWorkStore
from ai_foundation.guard import GuardCore
from ai_foundation.productization import FoundationConfig,backup,restore
from ai_foundation.store import SQLiteGuardStore

class Port:
 def __init__(self): self.v=''; self.n=0
 def execute(self,p): self.n+=1; self.v=p.text
 def observe(self,p): return self.v

def test_full_dr_restores_guard_and_work_without_replaying_verified_effect(tmp_path):
 root=tmp_path/'live'; root.mkdir(); cfg=FoundationConfig(str(root.resolve())); port=Port()
 gs=SQLiteGuardStore(root/cfg.guard_db); plan=TaskPlan('dr-run','write','target',text='done',canon_revision='c',effect_id='dr-effect')
 assert GuardCore(gs.load(),100,gs).execute(plan,CanonContract('repo','c'),port,'done')=='VERIFIED_COMPLETE'
 ws=SQLiteWorkStore(root/cfg.work_db); assert DurableWorkRunner(ws).execute('dr-job',[('step',lambda:'ok')]).value=='VERIFIED'
 (root/cfg.trace_file).write_text('evidence\n')
 backup(cfg,tmp_path/'backup'); restored=tmp_path/'restored'; restore(tmp_path/'backup',restored)
 rgs=SQLiteGuardStore(restored/cfg.guard_db); assert rgs.load().effects['dr-effect'].status.value=='VERIFIED'
 rws=SQLiteWorkStore(restored/cfg.work_db); assert rws.load('dr-job')[0].status.value=='VERIFIED'
 class NoReplay(Port):
  def execute(self,p): raise AssertionError('verified effect must not replay after DR')
 assert GuardCore(rgs.load(),100,rgs).execute(plan,CanonContract('repo','c'),NoReplay(),'done')=='VERIFIED_COMPLETE'
 assert (restored/cfg.trace_file).read_text()=='evidence\n'

def test_backup_restores_durable_inference_replay_authority(tmp_path):
 from ai_foundation.durable_inference import SQLiteInferenceAttemptStore
 root=tmp_path/'live2';root.mkdir();cfg=FoundationConfig(str(root.resolve()));attempts=SQLiteInferenceAttemptStore(root/cfg.inference_db)
 attempts.get_or_begin('request-1','cloud-a');attempts.complete('request-1','verified-result')
 backup(cfg,tmp_path/'backup2');restored=tmp_path/'restored2';restore(tmp_path/'backup2',restored)
 row=SQLiteInferenceAttemptStore(restored/cfg.inference_db).get('request-1')
 assert row.status=='VERIFIED' and row.result=='verified-result'
