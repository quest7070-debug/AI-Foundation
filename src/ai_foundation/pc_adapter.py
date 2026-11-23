"""Host-bound PC CONTROL adapter. It wraps an explicitly supplied ComputerPort only."""
from __future__ import annotations
from dataclasses import dataclass
from .capability_request import CapabilityRequest
from .computer_action import ActionMethod,ComputerActionSpecialist

@dataclass(frozen=True)
class BoundPCAction:
    action: str
    expected: str

class BoundComputerPort:
    def __init__(self,port,target): self._port=port; self._target=target
    def act(self,method,action,target):
        if target!=self._target: raise PermissionError('PC target outside bound capability')
        return self._port.act(method,action,target)
    def observe(self,target):
        if target!=self._target: raise PermissionError('PC target outside bound capability')
        return self._port.observe(target)

def build_pc_specialist(request:CapabilityRequest,port,allowed_methods):
    if request.capability!='PC_CONTROL': raise ValueError('PC_CONTROL capability required')
    methods=frozenset(ActionMethod(m) for m in allowed_methods)
    if not methods: raise PermissionError('no computer action capability')
    return ComputerActionSpecialist(BoundComputerPort(port,request.pc_target),methods)

def execute_pc(request:CapabilityRequest,port,allowed_methods,operation:BoundPCAction):
    if not isinstance(operation,BoundPCAction) or not operation.action or not operation.expected:
        raise ValueError('trusted PC operation required')
    specialist=build_pc_specialist(request,port,allowed_methods)
    return specialist.perform(operation.action,request.pc_target,operation.expected)
