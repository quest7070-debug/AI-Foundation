from ai_foundation.durable_work import *
from ai_foundation.research import *
from ai_foundation.capabilities import BoundComputeCapability,FixedComputeTool
from ai_foundation.data_specialist import DataSpecialist
class R:
 def research(self,q): return ResearchResult('facts',(Evidence('s','c'),),'')
class C:
 def compute(self,o,p): return 'analysis'
def test_research_data_effect_job_stops_and_resumes_without_repeating_research(tmp_path):
 store=SQLiteWorkStore(tmp_path/'job.db'); calls={'r':0,'e':0}
 research=ResearchSpecialist(R()); data=DataSpecialist(FixedComputeTool(BoundComputeCapability(C(),frozenset({'analyze'})),'analyze'))
 def r(): calls['r']+=1; return research.investigate('q').answer
 def d(): return data.analyze('facts').output
 def wait(): calls['e']+=1; return 'WAITING_HUMAN'
 runner=DurableWorkRunner(store)
 assert runner.execute('job',[('research',r),('data',d),('effect',wait)]) is WorkStatus.WAITING_HUMAN
 def effect(): calls['e']+=1; return 'VERIFIED_COMPLETE'
 assert DurableWorkRunner(SQLiteWorkStore(tmp_path/'job.db')).execute('job',[('research',r),('data',d),('effect',effect)]) is WorkStatus.VERIFIED
 assert calls=={'r':1,'e':2}
 assert [x.status for x in store.load('job')]==[WorkStatus.VERIFIED]*3
