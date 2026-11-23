from ai_foundation.orchestration import *
def test_plan_runs_in_order_and_finishes_verified():
 seen=[]; p=WorkPlan([WorkStep('r',lambda:seen.append('r') or 'ok'),WorkStep('c',lambda:seen.append('c') or 'ok')])
 assert p.execute() is WorkStatus.VERIFIED and seen==['r','c']
def test_waiting_human_stops_following_effects_and_can_resume():
 seen=[]
 def ask(): raise PermissionError('approval required')
 p=WorkPlan([WorkStep('read',lambda:seen.append('read') or 'ok'),WorkStep('effect',ask),WorkStep('after',lambda:seen.append('after') or 'ok')])
 assert p.execute() is WorkStatus.WAITING_HUMAN and seen==['read']
 p.steps[1].run=lambda:'approved'
 assert p.execute() is WorkStatus.VERIFIED and seen==['read','after']
def test_verified_steps_are_not_repeated_after_failure_resume():
 n={'a':0}
 def a(): n['a']+=1; return 'ok'
 p=WorkPlan([WorkStep('a',a),WorkStep('b',lambda:(_ for _ in ()).throw(RuntimeError('boom')))])
 assert p.execute() is WorkStatus.FAILED and n['a']==1
 p.steps[1].run=lambda:'ok'
 assert p.execute() is WorkStatus.VERIFIED and n['a']==1
