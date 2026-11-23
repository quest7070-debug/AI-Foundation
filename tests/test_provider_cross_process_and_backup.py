import multiprocessing as mp
from pathlib import Path
from ai_foundation.settings_service import SettingsService
from ai_foundation.provider_onboarding import ProbeResult
from ai_foundation.productization import FoundationConfig,backup,restore
class FileStore:
 def __init__(self,root):self.root=Path(root);self.root.mkdir(exist_ok=True)
 def _p(self,b):return self.root/b.replace(':','_')
 def save(self,b,s):self._p(b).write_text(s)
 def load(self,b):return self._p(b).read_text()
 def available(self,b):return self._p(b).exists()
 def delete(self,b):
  try:self._p(b).unlink();return True
  except FileNotFoundError:return False
class P:
 def probe(self,s,h=None):return ProbeResult(h or 'GROQ','ONLINE',80,'1m',70,'1d')
def _add(root,q):
 try:SettingsService(root,P(),FileStore(Path(root)/'keys')).add_provider('gsk_'+'X'*24);q.put('ok')
 except Exception as e:q.put(type(e).__name__+':'+str(e))
def test_cross_process_duplicate_is_serialized(tmp_path):
 q=mp.Queue(); ps=[mp.Process(target=_add,args=(str(tmp_path),q)) for _ in range(2)];[p.start() for p in ps];[p.join() for p in ps]
 out=sorted(q.get() for _ in ps); x=SettingsService(tmp_path,P(),FileStore(tmp_path/'keys'))
 assert out.count('ok')==1, out
 assert len(x.registry.bindings())==1 and any('already registered' in z for z in out), out
def test_provider_registry_is_in_backup_restore(tmp_path):
 root=tmp_path/'data';root.mkdir(); c=FoundationConfig(str(root)); __import__('sqlite3').connect(root/c.provider_db).execute('create table provider_state(v text)').connection.commit()
 dest=tmp_path/'backup'; m=backup(c,dest); assert c.provider_db in m['files']
 restored=tmp_path/'restored';restore(dest,restored);
 with __import__('sqlite3').connect(restored/c.provider_db) as db: assert db.execute("select name from sqlite_master where name='provider_state'").fetchone()==('provider_state',)
