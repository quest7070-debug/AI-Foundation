"""Durable Foundation notification-to-WebPush dispatch; transport failures never break core work."""
from __future__ import annotations
import json,os,tempfile
from pathlib import Path
from .notification_boundary import project_push
from .filesystem_lock import exclusive_file_lock

class PushDispatch:
 def __init__(self,transport,state_file:Path,max_seen=2048):self.transport=transport;self.state_file=state_file;self.max_seen=max(1,int(max_seen))
 def _seen(self):
  try:v=json.loads(self.state_file.read_text())
  except FileNotFoundError:return ()
  except (OSError,json.JSONDecodeError) as exc:raise RuntimeError('push dispatch state unreadable') from exc
  if not isinstance(v,list) or any(not isinstance(x,str) for x in v):raise RuntimeError('push dispatch state invalid')
  return tuple(dict.fromkeys(v))
 def _save(self,seen):
  self.state_file.parent.mkdir(parents=True,exist_ok=True)
  fd,name=tempfile.mkstemp(dir=self.state_file.parent,prefix='.push-seen-')
  tmp=Path(name)
  try:
   # Deduplication history is operational cache, not authority. Keep it bounded
   # so years of distinct incidents cannot grow the state file forever.
   bounded=list(seen)[-self.max_seen:]
   with os.fdopen(fd,'w') as f:json.dump(bounded,f);f.flush();os.fsync(f.fileno())
   os.replace(tmp,self.state_file)
  finally:
   try:tmp.unlink()
   except FileNotFoundError:pass
 def dispatch(self,human_payload):
  # Kernel serialization covers independent objects/processes, including their
  # read -> send -> persist transaction. The lock file must never be unlinked.
  with exclusive_file_lock(self.state_file.with_name(self.state_file.name+'.lock')):
   return self._dispatch(human_payload)
 def _dispatch(self,human_payload):
  history=list(self._seen());seen=set(history);attempted=set();sent=0;failed=0
  for n in project_push(human_payload,frozenset(seen)):
   # project_push snapshots the initial seen set; duplicate rows in the same
   # projection are not distinct deliveries.
   if n.key in seen or n.key in attempted:continue
   attempted.add(n.key)
   try:
    r=self.transport.deliver({'title':n.title,'body':n.body,'level':n.level,'key':n.key})
    if r.get('complete',r.get('sent',0)>0):
     seen.add(n.key);history.append(n.key);sent+=1
    else:failed+=1
   except Exception:failed+=1
  if sent:self._save(history)
  return {'sent_notices':sent,'failed_notices':failed}
