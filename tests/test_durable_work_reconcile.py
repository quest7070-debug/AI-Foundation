from ai_foundation.durable_work import *
def test_running_step_only_becomes_verified_after_verified_reconcile(tmp_path):
 s=SQLiteWorkStore(tmp_path/'w.db'); s.ensure('j',['effect']); assert s.claim_not_running('j',0)
 r=DurableWorkRunner(s)
 assert r.reconcile_running('j',0,lambda:'EFFECT_IN_PROGRESS') is WorkStatus.RUNNING
 assert s.load('j')[0].status is WorkStatus.RUNNING
 assert r.reconcile_running('j',0,lambda:'VERIFIED_COMPLETE') is WorkStatus.VERIFIED
 assert s.load('j')[0].status is WorkStatus.VERIFIED
def test_nonverified_reconcile_never_completes_work_step(tmp_path):
 s=SQLiteWorkStore(tmp_path/'w.db'); s.ensure('j',['effect']); s.claim_not_running('j',0)
 assert DurableWorkRunner(s).reconcile_running('j',0,lambda:'UNCERTAIN_RECONCILE_REQUIRED') is WorkStatus.RUNNING
