from dataclasses import dataclass
from enum import Enum
from typing import Callable
class WorkStatus(str,Enum):
 PLANNED='PLANNED'; RUNNING='RUNNING'; WAITING_HUMAN='WAITING_HUMAN'; VERIFIED='VERIFIED'; FAILED='FAILED'; CANCELLED='CANCELLED'
@dataclass
class WorkStep:
 name:str; run:Callable[[],str]; status:WorkStatus=WorkStatus.PLANNED; result:str=''
@dataclass
class WorkPlan:
 steps:list[WorkStep]
 def execute(self)->WorkStatus:
  for step in self.steps:
   if step.status is WorkStatus.VERIFIED: continue
   step.status=WorkStatus.RUNNING
   try: step.result=step.run()
   except PermissionError as e:
    step.result=str(e); step.status=WorkStatus.WAITING_HUMAN; return step.status
   except Exception as e:
    step.result=str(e); step.status=WorkStatus.FAILED; return step.status
   if step.result=='WAITING_HUMAN':
    step.status=WorkStatus.WAITING_HUMAN; return step.status
   step.status=WorkStatus.VERIFIED
  return WorkStatus.VERIFIED
