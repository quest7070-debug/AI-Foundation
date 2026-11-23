from ai_foundation.attachment_handoff import AttachmentHandoff,AttachmentRecord
from ai_foundation.capability_factory import build_daily_capability
from ai_foundation.capability_request import CapabilityRequest

def test_same_generic_handoff_grant_can_feed_non_vision_capability(tmp_path):
    root=tmp_path/'uploads';root.mkdir();p=root/'note.txt';p.write_text('hello')
    h=AttachmentHandoff(root,lambda aid,owner:AttachmentRecord(aid,owner,str(p)))
    grants=h.resolve('u',['f'])
    envelope=CapabilityRequest('CHAT',owner_id='u',attachments=grants,attachment_ids=('f',))
    routed=build_daily_capability({'X-Foundation-Capability':'SEARCH','X-Foundation-Owner':'u'},{},envelope)
    assert routed.attachments==grants and routed.attachment_ids==('f',)
    assert routed.capability=='SEARCH'
