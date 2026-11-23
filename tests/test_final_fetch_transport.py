import hashlib,hmac,json
from ai_foundation.librechat_signing_contract import sign_serialized_body
from scripts.chat_gateway import _verified_attachment_headers

def test_openai_style_final_serialized_body_verifies_at_gateway():
 body=json.dumps({'model':'foundation-auto','messages':[{'role':'user','content':'probe'}]},separators=(',',':')).encode()
 ts=100;secret='test-only';owner='isolated-owner';ids=('file-a',)
 sig=sign_serialized_body(secret,owner,body,attachment_ids=ids,capability='CHAT',timestamp=ts)
 headers={'X-Foundation-Owner':owner,'X-Foundation-Attachments':'["file-a"]','X-Foundation-Capability':'CHAT','X-Foundation-Attachment-Timestamp':str(ts),'X-Foundation-Attachment-Signature':sig}
 verified=_verified_attachment_headers(headers,secret,body,ts)
 assert verified['X-Foundation-Owner']==owner
 assert verified['X-Foundation-Attachments']=='["file-a"]'
 assert _verified_attachment_headers(headers,secret,body+b' ',ts)=={}
