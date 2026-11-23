from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol
class ActionMethod(IntEnum):
 API=1; MCP=2; DOM=3; VISION=4; COORDINATES=5
class ComputerPort(Protocol):
 def act(self,method:ActionMethod,action:str,target:str)->str: ...
 def observe(self,target:str)->str: ...
@dataclass
class ComputerActionSpecialist:
 port:ComputerPort
 allowed_methods:frozenset[ActionMethod]
 def perform(self,action:str,target:str,expected:str)->str:
  if not self.allowed_methods: raise PermissionError('no computer action capability')
  method=min(self.allowed_methods)
  result=self.port.act(method,action,target)
  observed=self.port.observe(target)
  if observed!=expected: raise RuntimeError('computer action not verified')
  return result
