from dataclasses import dataclass
import time
import uuid
@dataclass(frozen=True)
class StartupRecoveryReport:
 released_budget_reservations: tuple[str,...]
 released_budget_reservation_count: int = 0
 acquired: bool = True
class StartupRecovery:
 def __init__(self,guard_store,*,owner=None,min_age=60.0,lease_ttl=30.0,clock=time.time):
  self.guard_store=guard_store; self.owner=owner or f"startup-{uuid.uuid4()}"; self.min_age=min_age; self.lease_ttl=lease_ttl; self.clock=clock
 def run(self):
  now=self.clock()
  if not self.guard_store.try_claim_startup('recovery',self.owner,now,self.lease_ttl):
   return StartupRecoveryReport((),0,False)
  try:
   released_count,released=self.guard_store.recover_budget_reservations(now=now,min_age=self.min_age)
   return StartupRecoveryReport(released,released_count,True)
  finally:
   self.guard_store.release_startup('recovery',self.owner)
