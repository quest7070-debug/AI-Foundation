from ai_foundation.core import EffectIntent,EffectStatus,TaskPlan
from ai_foundation.guard import GuardCore
from ai_foundation.operator import snapshot
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.productization import FoundationConfig
from ai_foundation.store import SQLiteGuardStore

class ObserveOnlyPort:
    def __init__(self,value): self.value=value; self.execute_count=0; self.observe_count=0
    def execute(self,plan): self.execute_count+=1; raise AssertionError('reconciliation must not execute')
    def observe(self,plan): self.observe_count+=1; return self.value

def test_uncertain_to_verified_disappears_from_operator_attention(tmp_path):
    root=tmp_path/'data'; root.mkdir(); config=FoundationConfig(str(root.resolve()))
    store=SQLiteGuardStore(root/config.guard_db); state=store.load()
    effect=EffectIntent('effect-1','run-1','mailbox:test','sent-marker',EffectStatus.UNCERTAIN,0)
    state.effects[effect.effect_id]=effect; store.save(state)

    before=snapshot(config)
    assert before.effects.get('UNCERTAIN')==1
    assert any(x['id']=='effect-1' and x['status']=='UNCERTAIN' for x in before.attention)

    restarted=GuardCore(store.load(),store=store); port=ObserveOnlyPort('sent-marker')
    plan=TaskPlan(run_id='run-1',effect_id='effect-1',action='send_email',target='mailbox:test')
    result=OperatorActions(restarted).reconcile_effect('effect-1',plan,port)
    assert result.ok and result.status=='VERIFIED_COMPLETE'
    assert port.execute_count==0 and port.observe_count==1

    after=snapshot(config)
    assert after.effects.get('VERIFIED')==1
    assert after.effects.get('UNCERTAIN',0)==0
    assert not any(x['id']=='effect-1' for x in after.attention)
    assert store.load().effects['effect-1'].status is EffectStatus.VERIFIED
