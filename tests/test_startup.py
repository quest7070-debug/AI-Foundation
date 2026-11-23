from ai_foundation.startup import StartupRecovery
from ai_foundation.store import SQLiteGuardStore

def test_startup_recovery_is_single_owner_age_aware(tmp_path):
 s=SQLiteGuardStore(tmp_path/'g.db')
 with s._connect() as db:
  db.execute('insert into budget_reservations(run_id,amount,created) values (?,?,?)',('young',1,990))
  db.execute('insert into budget_reservations(run_id,amount,created) values (?,?,?)',('old',1,800))
 r=StartupRecovery(s,owner='a',min_age=100,clock=lambda:1000).run()
 assert r.acquired and r.released_budget_reservations==('old',) and r.released_budget_reservation_count==1
 with s._connect() as db: assert db.execute('select run_id from budget_reservations').fetchall()==[('young',)]

def test_second_startup_owner_defers_when_lease_active(tmp_path):
 s=SQLiteGuardStore(tmp_path/'g.db'); assert s.try_claim_startup('recovery','other',1000,30)
 r=StartupRecovery(s,owner='me',clock=lambda:1001).run()
 assert not r.acquired and r.released_budget_reservations==() and r.released_budget_reservation_count==0

def test_terminal_reservation_can_release_without_age_wait(tmp_path):
 from ai_foundation.core import EffectIntent,EffectStatus,GuardState
 s=SQLiteGuardStore(tmp_path/'g.db')
 st=GuardState(effects={'e':EffectIntent('e','r','x','ok',EffectStatus.FAILED,1)})
 s.save(st)
 with s._connect() as db: db.execute('insert into budget_reservations(run_id,amount,created) values (?,?,?)',('r',1,999))
 r=StartupRecovery(s,owner='a',min_age=100,clock=lambda:1000).run()
 assert r.released_budget_reservations==('r',) and r.released_budget_reservation_count==1


def test_startup_recovery_bounds_evidence_while_releasing_all(tmp_path):
 s=SQLiteGuardStore(tmp_path/'g.db'); n=25_000
 with s._connect() as db:
  db.executemany('insert into budget_reservations(run_id,amount,created) values (?,?,?)',((f'old-{i}',1,1) for i in range(n)))
 r=StartupRecovery(s,owner='bulk',min_age=100,clock=lambda:1000).run()
 assert r.acquired and r.released_budget_reservation_count==n and len(r.released_budget_reservations)==100
 with s._connect() as db: assert db.execute('select count(*) from budget_reservations').fetchone()[0]==0
