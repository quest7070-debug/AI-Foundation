import sqlite3,time
from dataclasses import dataclass

@dataclass(frozen=True)
class InferenceAttempt:
    request_id:str; binding:str; status:str; result:str|None

class SQLiteInferenceAttemptStore:
    """Durable evidence for non-idempotent/charged inference dispatch uncertainty."""
    def __init__(self,path,storage_admission=None):
        self.path=str(path); self.storage_admission=storage_admission
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS inference_attempts(request_id TEXT PRIMARY KEY,binding TEXT NOT NULL,status TEXT NOT NULL,result TEXT,updated_at REAL NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS idx_inference_terminal_updated ON inference_attempts(status,updated_at)')
    def _require_write(self):
        if self.storage_admission:self.storage_admission.require('inference evidence')
    def get_or_begin(self,request_id,binding):
        self._require_write()
        with sqlite3.connect(self.path) as db:
            row=db.execute('SELECT binding,status,result FROM inference_attempts WHERE request_id=?',(request_id,)).fetchone()
            if row:
                if row[1]=='FAILED':
                    db.execute("UPDATE inference_attempts SET binding=?,status='DISPATCHING',result=NULL,updated_at=? WHERE request_id=? AND status='FAILED'",(binding,time.time(),request_id))
                    return InferenceAttempt(request_id,binding,'NEW',None)
                if row[0]!=binding:
                    # A verified result is authoritative for the durable request regardless of
                    # which binding produced it. Only an in-flight/uncertain dispatch forbids rebind.
                    if row[1]=='VERIFIED': return InferenceAttempt(request_id,*row)
                    raise ValueError('inference binding changed for durable request')
                return InferenceAttempt(request_id,*row)
            db.execute('INSERT INTO inference_attempts VALUES(?,?,?,?,?)',(request_id,binding,'DISPATCHING',None,time.time()))
            return InferenceAttempt(request_id,binding,'NEW',None)
    def complete(self,request_id,result):
        self._require_write()
        with sqlite3.connect(self.path) as db:
            cur=db.execute("UPDATE inference_attempts SET status='VERIFIED',result=?,updated_at=? WHERE request_id=? AND status='DISPATCHING'",(result,time.time(),request_id))
            if cur.rowcount!=1:
                row=db.execute('SELECT binding,status,result FROM inference_attempts WHERE request_id=?',(request_id,)).fetchone()
                if not row: raise KeyError(request_id)
        return self.get(request_id)
    def failed(self,request_id):
        self._require_write()
        with sqlite3.connect(self.path) as db: db.execute("UPDATE inference_attempts SET status='FAILED',updated_at=? WHERE request_id=? AND status='DISPATCHING'",(time.time(),request_id))
        return self.get(request_id)
    def uncertain(self,request_id):
        self._require_write()
        with sqlite3.connect(self.path) as db: db.execute("UPDATE inference_attempts SET status='UNCERTAIN',updated_at=? WHERE request_id=? AND status='DISPATCHING'",(time.time(),request_id))
        return self.get(request_id)
    def get(self,request_id):
        with sqlite3.connect(self.path) as db: row=db.execute('SELECT binding,status,result FROM inference_attempts WHERE request_id=?',(request_id,)).fetchone()
        return InferenceAttempt(request_id,*row) if row else None
