import pytest
from ai_foundation.productization import FoundationConfig,backup,restore
from ai_foundation.authority_manifest import establish,verify,authority_files,MARKER

def seed(root,c):
 import sqlite3
 for name in authority_files(c):sqlite3.connect(root/name).close()
def test_first_bootstrap_is_allowed_but_established_loss_fails_closed(tmp_path):
 root=tmp_path/'data';root.mkdir();c=FoundationConfig(str(root.resolve()));assert not verify(root,c)['established'];seed(root,c);establish(root,c);assert verify(root,c)['established']
 (root/c.guard_db).unlink()
 with pytest.raises(RuntimeError,match='authoritative store missing'):verify(root,c)
def test_marker_is_backed_up_and_restored_with_authority(tmp_path):
 root=tmp_path/'data';root.mkdir();c=FoundationConfig(str(root.resolve()));seed(root,c);establish(root,c);backup(c,tmp_path/'b');restore(tmp_path/'b',tmp_path/'r');assert verify(tmp_path/'r',c)['established']
def test_corrupt_or_config_drifted_marker_fails_closed(tmp_path):
 root=tmp_path/'data';root.mkdir();c=FoundationConfig(str(root.resolve()));seed(root,c);establish(root,c);(root/MARKER).write_text('{bad')
 with pytest.raises(RuntimeError,match='marker unreadable'):verify(root,c)
