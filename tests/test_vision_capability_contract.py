import pytest
from ai_foundation.routing_capabilities import normalize_capability,ROUTE_CAPABILITIES,supports
from ai_foundation.capability_request import CapabilityRequest,AttachmentGrant
from ai_foundation.capability_topology import uses_llm_route

def test_vision_is_generic_route_and_aliases_normalize():
    assert 'VISION' in ROUTE_CAPABILITIES
    assert normalize_capability('image_analysis')=='VISION'
    assert normalize_capability('multimodal')=='VISION'
    assert uses_llm_route('VISION') is True

def test_vision_requires_trusted_attachment():
    with pytest.raises(ValueError): CapabilityRequest('VISION',owner_id='u')
    r=CapabilityRequest('VISION',owner_id='u',attachments=(AttachmentGrant('a','u','/trusted/a.jpg'),))
    assert r.capability=='VISION'

def test_provider_must_explicitly_advertise_vision():
    chat={'kind':'CLOUD','protocol':'openai-chat','model':'m','capabilities':('CHAT',)}
    vision={**chat,'capabilities':('CHAT','VISION')}
    assert not supports(chat,'VISION')
    assert supports(vision,'VISION')
