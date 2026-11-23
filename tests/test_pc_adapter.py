import pytest
from ai_foundation.pc_adapter import BoundPCAction,execute_pc
from ai_foundation.capability_request import CapabilityRequest
from ai_foundation.computer_action import ActionMethod
class P:
 def __init__(self):self.calls=[];self.state='done'
 def act(self,m,a,t):self.calls.append((m,a,t));return 'acted'
 def observe(self,t):self.calls.append(('observe',t));return self.state

def test_pc_adapter_binds_target_and_prefers_strongest_allowed_method():
 p=P();r=CapabilityRequest('PC_CONTROL',pc_target='desktop:primary')
 assert execute_pc(r,p,{ActionMethod.VISION,ActionMethod.MCP},BoundPCAction('open-settings','done'))=='acted'
 assert p.calls[0]==(ActionMethod.MCP,'open-settings','desktop:primary')

def test_pc_adapter_requires_trusted_operation_and_verified_readback():
 p=P();r=CapabilityRequest('PC_CONTROL',pc_target='desktop:primary')
 with pytest.raises(ValueError):execute_pc(r,p,{ActionMethod.API},None)
 p.state='wrong'
 with pytest.raises(RuntimeError,match='not verified'):execute_pc(r,p,{ActionMethod.API},BoundPCAction('set','done'))
