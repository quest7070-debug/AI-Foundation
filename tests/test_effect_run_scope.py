from ai_foundation.core import *
from ai_foundation.guard import GuardCore
from ai_foundation.store import SQLiteGuardStore
class P:
 def __init__(self): self.v={}; self.n=0
 def execute(self,p): self.n+=1; self.v[p.target]=p.text
 def observe(self,p): return self.v.get(p.target,'')
def test_run_cancellation_blocks_new_effect_ids(tmp_path):
 s=SQLiteGuardStore(tmp_path/'g.db'); g=GuardCore(GuardState(),store=s); p=P(); c=CanonContract('x','c')
 first=TaskPlan('run','write','a',text='1',canon_revision='c',effect_id='run:e1')
 assert g.execute(first,c,p,'1')=='VERIFIED_COMPLETE'
 g.cancel('run')
 second=TaskPlan('run','write','b',text='2',canon_revision='c',effect_id='run:e2')
 assert g.execute(second,c,p,'2')=='DENY' and p.n==1
