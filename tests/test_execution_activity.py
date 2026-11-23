import threading,time
from ai_foundation.execution_activity import ExecutionActivityRegistry
from ai_foundation.inference_service import GuardedInferenceService
from ai_foundation.compute_routing import ComputeRoute
from ai_foundation.core import TaskPlan,CanonContract,Decision

class G:
 def preflight(self,*a):return Decision.ALLOW
class R:
 settings=type('S',(),{'route_label':lambda s,b:'LOCAL / LOCAL'})()
 def choose(self,*a,**k):return ComputeRoute('local:x','LOCAL')
class L:
 def __init__(self,go):self.go=go
 def chat(self,text):self.go.wait(2);return 'ok'

def test_activity_exists_only_during_real_selected_execution():
 go=threading.Event(); a=ExecutionActivityRegistry(); svc=GuardedInferenceService(G(),R(),L(go),activity=a)
 plan=TaskPlan('job','compute','llm',text='x',canon_revision='c',effect_id='e')
 t=threading.Thread(target=lambda:svc.run(plan,CanonContract('c','c')));t.start()
 for _ in range(50):
  if a.current():break
  time.sleep(.01)
 row=a.current()[0];assert (row.job_id,row.binding,row.kind)==('job','local:x','LOCAL')
 go.set();t.join();assert a.current()==()

def test_cloud_activity_marks_route_active_by_semantic_function_not_display_label():
 from ai_foundation.human_view import HumanView,HumanRoute
 from ai_foundation.human_renderer import render
 from ai_foundation.execution_activity import ExecutionActivity
 a=ExecutionActivity('j','GENERAL','opaque-binding','CLOUD','GROQ / FREE',1.0)
 v=HumanView('RUNNING',(0,0,0,0,0),routes=(HumanRoute('GENERAL','GROQ / FREE',()),),activity=(a,))
 page=render(v,'responsive')
 assert 'panel-route route route-active' in page and 'USING NOW / GROQ / FREE' in page
