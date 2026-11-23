import pytest
from ai_foundation.file_execution import FileScope,ScopedFileExecution
from ai_foundation.guard import GuardCore
from ai_foundation.core import GuardState
class Port:
 def __init__(self):self.v={}
 def execute(self,p):self.v[p.target]=p.text
 def observe(self,p):return self.v.get(p.target,'')
def test_scope_is_host_bound_and_write_is_verified(tmp_path):
 p=Port();x=ScopedFileExecution(GuardCore(GuardState()),p,FileScope(str(tmp_path),write=True))
 assert x.write('r','a.txt','ok')=='VERIFIED_COMPLETE'
 assert x.read('r2','a.txt')=='ok'
 with pytest.raises(PermissionError):x.write('r3','../escape','x')
def test_readonly_scope_denies_write(tmp_path):
 x=ScopedFileExecution(GuardCore(GuardState()),Port(),FileScope(str(tmp_path),write=False))
 with pytest.raises(PermissionError):x.write('r','a','x')
