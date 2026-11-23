import os
from pathlib import Path
from scripts import librechat_secret_bootstrap as b

def test_materialize_is_private_atomic_and_not_return_secret(tmp_path,monkeypatch):
 class Store:
  def load(self,binding):
   assert binding=='foundation:attachment-handoff';return 'secret-value'
 monkeypatch.setattr(b,'MacOSNativeCredentialStore',lambda:Store())
 p=b.materialize('foundation:attachment-handoff',str(tmp_path/'secret'))
 assert p.read_text()=='secret-value'
 assert os.stat(p).st_mode & 0o777 == 0o400
 assert p.name=='secret'
 assert not (tmp_path/'secret.tmp').exists()

def test_missing_keychain_secret_fails_without_file(tmp_path,monkeypatch):
 class Store:
  def load(self,binding): raise KeyError(binding)
 monkeypatch.setattr(b,'MacOSNativeCredentialStore',lambda:Store())
 target=tmp_path/'secret'
 try:b.materialize('foundation:attachment-handoff',str(target))
 except KeyError:pass
 else:assert False
 assert not target.exists()
