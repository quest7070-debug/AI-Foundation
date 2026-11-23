import pytest
from ai_foundation.durable_work import *
from ai_foundation.work_runtime import *
def test_runtime_refuses_orphan_without_reconciler(tmp_path):
 s=SQLiteWorkStore(tmp_path/'w.db'); s.ensure('j',['e']); s.claim_not_running('j',0)
 with pytest.raises(RuntimeError,match='requires reconciliation'): DurableWorkRuntimeCall(DurableWorkRunner(s)).run('j',[('e',lambda:'bad')])
def test_runtime_reconciles_orphan_then_completes_without_execute(tmp_path):
 s=SQLiteWorkStore(tmp_path/'w.db'); s.ensure('j',['e']); s.claim_not_running('j',0); n={'x':0}
 out=DurableWorkRuntimeCall(DurableWorkRunner(s)).run('j',[('e',lambda:n.__setitem__('x',1))],{'e':lambda:'VERIFIED_COMPLETE'})
 assert out=='VERIFIED_COMPLETE' and n['x']==0
def test_runtime_does_not_report_running_as_success(tmp_path):
 s=SQLiteWorkStore(tmp_path/'w.db'); s.ensure('j',['e']); s.claim_not_running('j',0)
 with pytest.raises(RuntimeError,match='reconciliation incomplete'): DurableWorkRuntimeCall(DurableWorkRunner(s)).run('j',[('e',lambda:'bad')],{'e':lambda:'EFFECT_IN_PROGRESS'})
