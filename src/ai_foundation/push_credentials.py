"""WebPush credentials through Foundation's native secret boundary."""
from __future__ import annotations
from dataclasses import dataclass
import json

BINDING='notification:webpush:vapid'

@dataclass(frozen=True,repr=False)
class VapidCredential:
 private_key:str
 public_key:str
 subject:str
 def __repr__(self):return "VapidCredential(private_key=<redacted>, public_key=<redacted>, subject=<redacted>)"

class VapidCredentialStore:
 def __init__(self,secret_store,binding:str=BINDING):self.secret_store=secret_store;self.binding=binding
 def save(self,credential:VapidCredential):
  if not credential.private_key or not credential.public_key or not credential.subject:raise ValueError('complete VAPID credential required')
  self.secret_store.save(self.binding,json.dumps({'private_key':credential.private_key,'public_key':credential.public_key,'subject':credential.subject},separators=(',',':')))
 def load(self)->VapidCredential:
  raw=self.secret_store.load(self.binding)
  try:d=json.loads(raw)
  except Exception as exc:raise RuntimeError('invalid stored VAPID credential') from exc
  if not isinstance(d,dict) or not all(isinstance(d.get(k),str) and d[k] for k in ('private_key','public_key','subject')):raise RuntimeError('invalid stored VAPID credential')
  return VapidCredential(d['private_key'],d['public_key'],d['subject'])
 def available(self)->bool:return self.secret_store.available(self.binding)
