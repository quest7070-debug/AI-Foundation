from ai_foundation.capability_execution import CapabilityExecutor
from ai_foundation.capability_request import CapabilityRequest,AttachmentGrant
from ai_foundation.vision_execution import VisionObservation
class Port:
 def observe(self,request,text):return VisionObservation("vision:"+text,"fake",False)
def test_executor_dispatches_vision_without_domain_semantics():
 r=CapabilityRequest("VISION",owner_id="u",attachments=(AttachmentGrant("a","u","/trusted/a.png"),))
 assert CapabilityExecutor(None,None,vision_port=Port()).execute(r,"describe","run")=="vision:describe"
def test_executor_fails_closed_without_vision_port():
 import pytest
 r=CapabilityRequest("VISION",owner_id="u",attachments=(AttachmentGrant("a","u","/trusted/a.png"),))
 with pytest.raises(RuntimeError,match="VISION unavailable"):CapabilityExecutor(None,None).execute(r,"describe","run")
