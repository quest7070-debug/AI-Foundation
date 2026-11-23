"""Replaceable WebPush transport/storage. Optional pywebpush dependency is loaded only on send."""
from __future__ import annotations
from dataclasses import dataclass
import json,os,threading,hashlib,tempfile
from .filesystem_lock import exclusive_file_lock
from pathlib import Path

@dataclass(frozen=True)
class WebPushConfig:
 private_key:str; public_key:str; subject:str; subscriptions_file:Path

class SubscriptionStoreCorrupt(RuntimeError):pass

class SubscriptionStore:
 def __init__(self,path:Path):self.path=path;self._lock=threading.RLock()
 def load(self)->dict[str,dict]:
  with self._lock:
   try:v=json.loads(self.path.read_text())
   except FileNotFoundError:return {}
   except (json.JSONDecodeError,OSError) as exc:raise SubscriptionStoreCorrupt('push subscription store unreadable') from exc
   if not isinstance(v,dict):raise SubscriptionStoreCorrupt('push subscription store has invalid shape')
   return v
 def save(self,items:dict[str,dict]):
  with self._lock:
   self.path.parent.mkdir(parents=True,exist_ok=True); tmp=self.path.with_suffix(self.path.suffix+'.tmp')
   fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
   try:
    with os.fdopen(fd,'w') as f:f.write(json.dumps(items,separators=(',',':')));f.flush();os.fsync(f.fileno())
    os.replace(tmp,self.path)
    dfd=os.open(self.path.parent,os.O_RDONLY)
    try:os.fsync(dfd)
    finally:os.close(dfd)
   finally:
    try:tmp.unlink()
    except FileNotFoundError:pass
 def put(self,subscription:dict):
  endpoint=str(subscription.get('endpoint') or '')
  keys=subscription.get('keys') if isinstance(subscription.get('keys'),dict) else {}
  if not endpoint.startswith('https://') or not keys.get('p256dh') or not keys.get('auth'):raise ValueError('invalid push subscription')
  with self._lock:
   items=self.load();items[endpoint]={'endpoint':endpoint,'keys':{'p256dh':str(keys['p256dh']),'auth':str(keys['auth'])}};self.save(items)
 def remove(self,endpoint:str):
  with self._lock:
   items=self.load();items.pop(endpoint,None);self.save(items)

class PushDependencyUnavailable(RuntimeError):pass

class WebPushTransport:
 def __init__(self,config:WebPushConfig,*,max_acknowledged_notices=2048):
  self.config=config;self.store=SubscriptionStore(config.subscriptions_file)
  self.ack_file=Path(str(config.subscriptions_file)+'.acks.json')
  self.max_acknowledged_notices=max(1,int(max_acknowledged_notices))
 def send(self,subscription:dict,payload:dict):
  try:from pywebpush import webpush
  except ImportError as exc:raise PushDependencyUnavailable('pywebpush is not installed') from exc
  webpush(subscription_info=subscription,data=json.dumps(payload,ensure_ascii=False),vapid_private_key=self.config.private_key,vapid_claims={'sub':self.config.subject},timeout=10)
 @staticmethod
 def _fingerprint(subscription):
  # A rotated key at the same endpoint is a different delivery target. Only
  # opaque fingerprints, never endpoints/keys/payloads, enter acknowledgement state.
  raw=json.dumps(subscription,sort_keys=True,separators=(',',':')).encode('utf-8')
  return hashlib.sha256(raw).hexdigest()
 def _load_acknowledgements(self):
  try:state=json.loads(self.ack_file.read_text(encoding='utf-8'))
  except FileNotFoundError:return {}
  except (OSError,json.JSONDecodeError) as exc:
   raise SubscriptionStoreCorrupt('push acknowledgement store unreadable') from exc
  if not isinstance(state,dict) or state.get('version')!=1 or not isinstance(state.get('notices'),dict):
   raise SubscriptionStoreCorrupt('push acknowledgement store invalid')
  rows=state['notices']
  for key,values in rows.items():
   if not isinstance(key,str) or not isinstance(values,list) or any(
     not isinstance(x,str) or len(x)!=64 or any(c not in '0123456789abcdef' for c in x) for x in values):
    raise SubscriptionStoreCorrupt('push acknowledgement store invalid')
  return rows
 def _save_acknowledgements(self,rows):
  self.ack_file.parent.mkdir(parents=True,exist_ok=True)
  bounded=dict(list(rows.items())[-self.max_acknowledged_notices:])
  fd,name=tempfile.mkstemp(dir=self.ack_file.parent,prefix='.push-acks-')
  tmp=Path(name)
  try:
   with os.fdopen(fd,'w') as stream:
    json.dump({'version':1,'notices':bounded},stream,separators=(',',':'))
    stream.flush();os.fsync(stream.fileno())
   os.replace(tmp,self.ack_file)
   parent=os.open(self.ack_file.parent,os.O_RDONLY)
   try:os.fsync(parent)
   finally:os.close(parent)
  finally:tmp.unlink(missing_ok=True)
 def deliver(self,payload:dict)->dict:
  key=payload.get('key')
  if not isinstance(key,str) or not key:
   # Unkeyed callers retain the original best-effort summary contract.
   return self._deliver(payload)
  with exclusive_file_lock(Path(str(self.ack_file)+'.lock')):
   return self._deliver(payload,key=key)
 def _deliver(self,payload,key=None):
  items=self.store.load();sent=0;expired=[];failed=0
  rows=self._load_acknowledgements() if key is not None else {}
  acknowledged=set(rows.get(key,()))
  current={self._fingerprint(sub) for sub in items.values()}
  acknowledged.intersection_update(current)
  for endpoint,sub in items.items():
   fingerprint=self._fingerprint(sub)
   if key is not None and fingerprint in acknowledged:continue
   try:
    self.send(sub,payload);sent+=1
   except Exception as exc:
    status=getattr(getattr(exc,'response',None),'status_code',None)
    if status in {404,410}:expired.append(endpoint)
    elif isinstance(exc,PushDependencyUnavailable):raise
    else:failed+=1
   else:
    if key is not None:
     acknowledged.add(fingerprint)
     rows.pop(key,None);rows[key]=sorted(acknowledged)
     # Commit every independently accepted target before attempting the next.
     # A crash before this commit can still duplicate that one target.
     self._save_acknowledgements(rows)
  if expired:
   with self.store._lock:
    latest=self.store.load()
    for endpoint in expired:
     # Do not remove a concurrent replacement at the same endpoint.
     if latest.get(endpoint)==items[endpoint]:latest.pop(endpoint,None)
    self.store.save(latest)
  result={'sent':sent,'expired':len(expired),'subscriptions':len(items)}
  if key is not None:
   # Do not globally settle an unseen notice when there are no subscriptions.
   remaining=self.store.load()
   result['complete']=(bool(remaining) and failed==0 and all(
    self._fingerprint(sub) in acknowledged for sub in remaining.values()))
  return result
