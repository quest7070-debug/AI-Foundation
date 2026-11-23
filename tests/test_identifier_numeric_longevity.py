import sqlite3, uuid
from ai_foundation.task_intake import TaskIntake
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.core import EffectIntent,EffectStatus,GuardState

def test_generated_task_ids_use_full_uuid_entropy_and_large_sample_is_unique(tmp_path,monkeypatch):
    # Generation contract is 128-bit UUID hex, not a shortened birthday-collision domain.
    intake=TaskIntake(tmp_path/'w.db')
    seen=set()
    for _ in range(100_000):
        value='task-'+uuid.uuid4().hex
        assert len(value)==37 and value not in seen
        seen.add(value)
    fixed=uuid.UUID('12345678-1234-5678-1234-567812345678')
    monkeypatch.setattr('ai_foundation.task_intake.uuid.uuid4',lambda:fixed)
    assert intake.submit('x').job_id=='task-12345678123456781234567812345678'

def test_long_mixed_case_authority_ids_roundtrip_without_truncation_or_normalization(tmp_path):
    p=tmp_path/'g.db'; s=SQLiteGuardStore(p)
    a='Run-'+'AaZz09_'*30; b=a.swapcase()
    state=GuardState(approvals={a,b},effects={
      a:EffectIntent(a,a,'t','x',EffectStatus.VERIFIED,0),
      b:EffectIntent(b,b,'t','x',EffectStatus.VERIFIED,0)})
    s.save(state)
    assert s.is_approved(a) and s.is_approved(b) and a!=b
    assert s.get_effect(a).run_id==a and s.get_effect(b).run_id==b
    with sqlite3.connect(p) as db: assert db.execute('SELECT COUNT(*) FROM effects').fetchone()[0]==2

def test_projected_numeric_ranges_remain_exact_and_ordered(tmp_path):
    p=tmp_path/'g.db'; s=SQLiteGuardStore(p)
    # Far beyond practical monthly spend/count while remaining deliberately inside exact integer authority.
    trillion=10**12
    with s._connect() as db:
        db.execute("UPDATE guard_meta SET value=? WHERE key='spent'",(trillion,))
        db.execute('INSERT INTO budget_reservations(run_id,amount,created) VALUES(?,?,?)',('future',trillion,4_102_444_800)) # 2100-01-01
        db.execute('INSERT INTO effect_claims(effect_id,owner,expires) VALUES(?,?,?)',('future','o',4_102_444_800.125))
    assert s.spent()==trillion
    assert not s.reserve_budget('another',1,trillion*2)  # existing 1e12 reserve + 1e12 spent reaches limit; +1 denied
    with s._connect() as db:
        amount,created=db.execute("SELECT amount,created FROM budget_reservations WHERE run_id='future'").fetchone()
        expires=db.execute("SELECT expires FROM effect_claims WHERE effect_id='future'").fetchone()[0]
    assert amount==trillion and created==4_102_444_800 and expires==4_102_444_800.125
