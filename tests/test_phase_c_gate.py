from ai_foundation.durable_work import *
from ai_foundation.work_runtime import DurableWorkRuntimeCall
def test_multi_effect_recovery_gate(tmp_path):
 s=SQLiteWorkStore(tmp_path/'w.db'); calls={'read':0,'e1':0,'e2':0}
 def read(): calls['read']+=1; return 'ok'
 def e1(): calls['e1']+=1; return 'ok'
 def e2(): calls['e2']+=1; return 'ok'
 r=DurableWorkRunner(s)
 # first two complete; emulate process loss after second external effect began
 assert r.execute('j',[('read',read),('e1',e1)]) is WorkStatus.VERIFIED
 s.ensure('j',['read','e1','e2']); assert s.claim_not_running('j',2); calls['e2']+=1
 rt=DurableWorkRuntimeCall(DurableWorkRunner(SQLiteWorkStore(tmp_path/'w.db')))
 assert rt.run('j',[('read',read),('e1',e1),('e2',e2)],{'e2':lambda:'VERIFIED_COMPLETE'})=='VERIFIED_COMPLETE'
 assert calls=={'read':1,'e1':1,'e2':1}
 assert all(x.status is WorkStatus.VERIFIED for x in s.load('j'))
