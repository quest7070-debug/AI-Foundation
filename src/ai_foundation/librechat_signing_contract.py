"""Reference contract for signing the exact serialized LibreChat OpenAI request body."""
import hashlib,hmac,json,time

def sign_serialized_body(secret,owner,serialized_body,*,attachment_ids=(),capability='CHAT',scope='',long_running=False,timestamp=None):
 if not secret or not owner: raise ValueError('secret and owner required')
 if not isinstance(serialized_body,(bytes,bytearray)):raise TypeError('serialized body bytes required')
 ids=tuple(attachment_ids);canonical=json.dumps(ids,separators=(',',':'))
 cap=capability.upper();ts=int(time.time() if timestamp is None else timestamp)
 digest=hashlib.sha256(bytes(serialized_body)).hexdigest()
 msg=f"v2\n{owner}\n{canonical}\n{cap}\n{scope}\n{1 if long_running else 0}\n{ts}\n{digest}".encode()
 return hmac.new(secret.encode(),msg,hashlib.sha256).hexdigest()
