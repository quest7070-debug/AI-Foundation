import sqlite3

from ai_foundation.operator import snapshot, render_json
from ai_foundation.productization import FoundationConfig


def test_operator_snapshot_exposes_actionable_state(tmp_path):
    from ai_foundation.store import SQLiteGuardStore
    from ai_foundation.durable_work import SQLiteWorkStore
    from ai_foundation.core import GuardState,EffectIntent,EffectStatus
    root=tmp_path/'data';root.mkdir();c=FoundationConfig(str(root.resolve()))
    g=SQLiteGuardStore(root/c.guard_db);g.save(GuardState(effects={'a':EffectIntent('a','r1','t','x',EffectStatus.VERIFIED,0),'b':EffectIntent('b','r2','t','x',EffectStatus.EXECUTING,0)}));g.transition_effect('b',EffectStatus.EXECUTING,EffectStatus.UNCERTAIN)
    w=SQLiteWorkStore(root/c.work_db);w.ensure('j',['a','b']);w.set('j',0,__import__('ai_foundation.orchestration',fromlist=['WorkStatus']).WorkStatus.WAITING_HUMAN);w.set('j',1,__import__('ai_foundation.orchestration',fromlist=['WorkStatus']).WorkStatus.VERIFIED)
    (root/c.trace_file).write_text('',encoding='utf-8')
    snap=snapshot(c)
    assert snap.effects['VERIFIED']==1 and snap.effects['UNCERTAIN']==1 and snap.waiting_human==1 and snap.trace_present

def test_operator_snapshot_new_host_is_read_only(tmp_path):
    root = tmp_path / "missing"

    s = snapshot(FoundationConfig(str(root.resolve())))

    assert s.effects == {}
    assert s.work == {}
    assert not s.trace_present
    assert not root.exists()

def test_effect_attention_carries_authoritative_recency(tmp_path):
 import sqlite3
 from ai_foundation.productization import FoundationConfig
 from ai_foundation.store import SQLiteGuardStore
 from ai_foundation.core import GuardState,EffectIntent,EffectStatus
 from ai_foundation.operator import snapshot
 c=FoundationConfig(str(tmp_path.resolve()));s=SQLiteGuardStore(tmp_path/c.guard_db)
 s.save(GuardState(effects={'e':EffectIntent('e','r','t','x',EffectStatus.EXECUTING,0)}));s.transition_effect('e',EffectStatus.EXECUTING,EffectStatus.UNCERTAIN)
 row=next(x for x in snapshot(c).attention if x['kind']=='effect')
 assert row['id']=='e' and row['updated_at']>0

def test_running_work_is_activity_not_operator_notification(tmp_path):
 from ai_foundation.productization import FoundationConfig
 from ai_foundation.durable_work import SQLiteWorkStore
 from ai_foundation.orchestration import WorkStatus
 c=FoundationConfig(str(tmp_path.resolve()));w=SQLiteWorkStore(tmp_path/c.work_db);w.ensure('j',['step']);w.set('j',0,WorkStatus.RUNNING)
 s=snapshot(c);assert s.work['RUNNING']==1 and not any(x.get('status')=='RUNNING' for x in s.attention)
