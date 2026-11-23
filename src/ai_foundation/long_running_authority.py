"""Durable host-owned authority for asynchronous Foundation work.

Hatchet stores a job identity only. The executable CapabilityRequest is persisted and
reconstructed here by the trusted host; runtime payloads cannot mint authority.
"""
from __future__ import annotations
import json,sqlite3,time
from pathlib import Path
from .capability_request import CapabilityRequest

_ALLOWED=frozenset({'SEARCH','CODE','DATA','PC_CONTROL'})
_FIELDS=('capability','owner_id','repo_root','file_read_root','file_write_root','data_operation','data_backend','pc_target','long_running','attachment_ids')

class LongRunningAuthorityStore:
 def __init__(self,path):
  self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
  with sqlite3.connect(self.path) as d:d.execute('CREATE TABLE IF NOT EXISTS long_running_authority(job_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, request_json TEXT NOT NULL, created_at REAL NOT NULL)')
 def put(self,job_id,request):
  if not job_id or not request.long_running or request.capability not in _ALLOWED: raise ValueError('invalid long-running authority')
  if request.attachments: raise PermissionError('resolved attachment paths cannot be persisted as long-running authority')
  data={k:getattr(request,k) for k in _FIELDS};data['attachment_ids']=list(data['attachment_ids'])
  data['schema_version']=2
  raw=json.dumps(data,separators=(',',':'),sort_keys=True)
  with sqlite3.connect(self.path) as d:
   row=d.execute('SELECT owner_id,request_json FROM long_running_authority WHERE job_id=?',(job_id,)).fetchone()
   if row is None:
    d.execute('INSERT INTO long_running_authority VALUES(?,?,?,?)',(job_id,request.owner_id,raw,time.time()))
   elif row!=(request.owner_id,raw):
    # Exact v1 grants predate data_backend/schema_version. Accept only a
    # semantically identical replay that cannot invent the omitted backend.
    legacy=json.loads(row[1])
    v1={k:data[k] for k in _FIELDS if k!='data_backend'}
    if not (row[0]==request.owner_id and legacy==v1 and not request.data_backend):
     raise PermissionError('long-running authority replay mismatch')
   # Exact replay is intentionally a no-op. The stable job identity is also the
   # Hatchet idempotency key, so retry after an ambiguous trigger outcome cannot
   # expand authority or create a second logical grant.
 def get(self,job_id,owner_id,capability):
  with sqlite3.connect(self.path) as d:r=d.execute('SELECT owner_id,request_json FROM long_running_authority WHERE job_id=?',(job_id,)).fetchone()
  if not r: raise KeyError(job_id)
  if r[0]!=owner_id: raise PermissionError('long-running owner mismatch')
  data=json.loads(r[1])
  version=data.pop('schema_version',1)
  if version not in (1,2): raise ValueError('unsupported authority schema version')
  data['attachment_ids']=tuple(data.get('attachment_ids',()))
  req=CapabilityRequest(**data)
  if req.capability!=capability: raise PermissionError('long-running capability mismatch')
  return req
 def forget(self,job_id):
  with sqlite3.connect(self.path) as d:d.execute('DELETE FROM long_running_authority WHERE job_id=?',(job_id,))

class DurableLongRunningExecutor:
 def __init__(self,authority_store,capability_executor):self.authority_store=authority_store;self.capability_executor=capability_executor
 def execute_long_running(self,job_id,capability,owner_id,text):
  req=self.authority_store.get(job_id,owner_id,capability)
  result=self.capability_executor.execute(req,text,job_id)
  if capability=='CODE':
   # Inspect is observational. Changes require both a verified Guard write and
   # a successful independent test; JSON text alone is not a success signal.
   try: receipt=json.loads(result)
   except (TypeError,ValueError) as exc: raise ValueError('invalid CODE receipt') from exc
   if not isinstance(receipt,dict) or receipt.get('status') not in {'INSPECTED','VERIFIED_COMPLETE'}:
    return {'status':'FAILED_VERIFICATION','result':result}
   if receipt.get('operation')=='change' and receipt['status']!='VERIFIED_COMPLETE':
    return {'status':'FAILED_VERIFICATION','result':result}
  return {'status':'VERIFIED_COMPLETE','result':result}
