from ai_foundation.core import *
from ai_foundation.guard import GuardCore
from ai_foundation.store import SQLiteGuardStore

class Port:
 def __init__(self): self.v="old"; self.calls=0
 def execute(self,p): self.calls+=1; self.v=p.text
 def observe(self,p): return self.v

def test_precondition_conflict_releases_budget_reservation(tmp_path):
 s=SQLiteGuardStore(tmp_path/'g.db'); p=Port(); plan=TaskPlan('r','write','x',text='new',paid_cost=5,canon_revision='c',target_precondition='expected')
 assert GuardCore(s.load(),10,s).execute(plan,CanonContract('x','c'),p,'new')=='TARGET_PRECONDITION_CONFLICT'
 with s._connect() as db: assert db.execute('select count(*) from budget_reservations').fetchone()[0] == 0

def test_target_busy_releases_budget_reservation(tmp_path):
 s=SQLiteGuardStore(tmp_path/'g2.db'); p=Port(); now=__import__('time').time(); assert s.try_claim_target('x','other',now,30)
 plan=TaskPlan('r2','write','x',text='new',paid_cost=5,canon_revision='c',exclusive_target=True)
 assert GuardCore(s.load(),10,s).execute(plan,CanonContract('x','c'),p,'new')=='TARGET_IN_PROGRESS'
 with s._connect() as db: assert db.execute('select count(*) from budget_reservations').fetchone()[0] == 0

def test_already_verified_paid_run_does_not_leave_new_reservation(tmp_path):
 s=SQLiteGuardStore(tmp_path/'g3.db'); p=Port(); plan=TaskPlan('r3','write','x',text='new',paid_cost=5,canon_revision='c')
 g=GuardCore(s.load(),10,s); assert g.execute(plan,CanonContract('x','c'),p,'new')=='VERIFIED_COMPLETE'
 assert GuardCore(s.load(),10,s).execute(plan,CanonContract('x','c'),p,'new')=='VERIFIED_COMPLETE'
 with s._connect() as db: assert db.execute('select count(*) from budget_reservations').fetchone()[0] == 0
