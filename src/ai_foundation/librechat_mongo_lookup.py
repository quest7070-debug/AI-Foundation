"""Read-only LibreChat attachment metadata lookup through its host-owned Mongo container."""
from __future__ import annotations
import json,re,subprocess

class LibreChatMongoQuery:
    def __init__(self,container='chat-mongodb',database='LibreChat',timeout=5,docker_bin='/usr/local/bin/docker'):
        self.container=container;self.database=database;self.timeout=timeout;self.docker_bin=docker_bin
    def __call__(self,query):
        allowed={'file_id','user','tenantId'}
        # Mongo is a separate authorization boundary: a caller that forgets
        # the authenticated user must never query file metadata account-wide.
        if not isinstance(query,dict) or not {'file_id','user'} <= set(query) or set(query)-allowed:return None
        if any(not isinstance(v,str) or not v or len(v)>256 for v in query.values()):return None
        if re.fullmatch(r'[0-9a-fA-F]{24}',query['user']) is None:return None
        safe=dict(query)
        owner=safe.pop('user',None)
        q=json.dumps(safe,separators=(',',':'))
        owner_js=json.dumps(owner)
        js='const q='+q+';const owner='+owner_js+';if(owner){if(!/^[0-9a-fA-F]{24}$/.test(owner))quit(2);q.user=ObjectId(owner)};const d=db.files.findOne(q,{_id:0,file_id:1,user:1,filepath:1,text:1,type:1,filename:1,source:1,tenantId:1});if(d)print(JSON.stringify(d));'
        try:
            cp=subprocess.run([self.docker_bin,'exec',self.container,'mongosh','--quiet',self.database,'--eval',js],capture_output=True,text=True,timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired):
            # A missing/stalled Mongo host is unavailable, never owner evidence.
            return None
        if cp.returncode:return None
        line=next((x for x in reversed(cp.stdout.splitlines()) if x.lstrip().startswith('{')),None)
        if not line:return None
        try:
            out=json.loads(line)
        except json.JSONDecodeError:return None
        if not isinstance(out,dict):return None
        # A successful process exit or a trusted query string is not enough:
        # bind returned metadata back to the authenticated owner and file.
        # Mismatched results must never reach the higher-level file adapter.
        returned_owner=out.get('user')
        if (out.get('file_id')!=query['file_id']
                or not isinstance(returned_owner,str)
                or returned_owner.lower()!=owner.lower()
                or ('tenantId' in query and out.get('tenantId')!=query['tenantId'])):
            return None
        return out

