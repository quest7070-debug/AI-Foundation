import pytest
from ai_foundation.attachment_handoff import AttachmentHandoff,AttachmentRecord

def test_owner_scoped_resolution(tmp_path):
 root=tmp_path/"uploads";root.mkdir();p=root/"a.txt";p.write_text("x")
 records={"f1":AttachmentRecord("f1","u1",str(p))}
 out=AttachmentHandoff(root,records.get).resolve("u1",["f1"])
 assert out[0].path==str(p.resolve()) and out[0].owner_id=="u1"

def test_cross_owner_denied(tmp_path):
 root=tmp_path/"uploads";root.mkdir();p=root/"a";p.write_text("x")
 h=AttachmentHandoff(root,lambda _:AttachmentRecord("f","u1",str(p)))
 with pytest.raises(PermissionError):h.resolve("u2",["f"])

def test_path_outside_root_denied(tmp_path):
 root=tmp_path/"uploads";root.mkdir();p=tmp_path/"secret";p.write_text("x")
 h=AttachmentHandoff(root,lambda _:AttachmentRecord("f","u",str(p)))
 with pytest.raises(PermissionError):h.resolve("u",["f"])

def test_missing_duplicate_and_empty_owner_fail_closed(tmp_path):
 root=tmp_path/"uploads";root.mkdir();p=root/"a";p.write_text("x")
 h=AttachmentHandoff(root,lambda x: AttachmentRecord(x,"u",str(p)) if x=="f" else None)
 with pytest.raises(FileNotFoundError):h.resolve("u",["missing"])
 with pytest.raises(ValueError):h.resolve("u",["f","f"])
 with pytest.raises(ValueError):h.resolve("",["f"])

def test_text_record_is_materialized_into_private_integration_handoff(tmp_path):
 root=tmp_path/'uploads';root.mkdir()
 h=AttachmentHandoff(root,lambda *_:AttachmentRecord('f','u',text='trusted text'))
 g=h.resolve('u',['f'])[0]
 p=__import__('pathlib').Path(g.path)
 assert p.read_text()=='trusted text' and p.parent.name=='.foundation-handoff'
 assert (p.stat().st_mode & 0o777)==0o600

def test_cleanup_removes_only_expired_materialized_files(tmp_path):
 import os
 root=tmp_path/'uploads';root.mkdir();h=AttachmentHandoff(root,lambda *_:AttachmentRecord('f','u',text='x'))
 p=__import__('pathlib').Path(h.resolve('u',['f'])[0].path);source=root/'source.txt';source.write_text('keep')
 os.utime(p,(100,100)); assert h.cleanup(max_age_seconds=50,now=200)==(p.name,)
 assert not p.exists() and source.read_text()=='keep'

def test_cleanup_preserves_recent_symlink_and_directory(tmp_path):
 import os
 root=tmp_path/'uploads';root.mkdir();h=AttachmentHandoff(root,lambda *_:None);d=h.handoff_root;d.mkdir()
 recent=d/'recent.txt';recent.write_text('x');os.utime(recent,(190,190))
 sub=d/'sub';sub.mkdir();target=root/'target';target.write_text('x');link=d/'link';link.symlink_to(target)
 assert h.cleanup(max_age_seconds=50,now=200)==()
 assert recent.exists() and sub.exists() and link.is_symlink()

def test_text_materialization_is_atomic_and_leaves_no_tmp(tmp_path):
 root=tmp_path/'uploads';root.mkdir();h=AttachmentHandoff(root,lambda *_:AttachmentRecord('f','u',text='new'))
 p=__import__('pathlib').Path(h.resolve('u',['f'])[0].path)
 assert p.read_text()=='new' and not list(p.parent.glob('*.tmp'))

def test_active_lease_blocks_expiry_until_release(tmp_path):
 import os
 root=tmp_path/'uploads';root.mkdir();h=AttachmentHandoff(root,lambda *_:AttachmentRecord('f','u',text='x'))
 grant=h.resolve('u',['f'])[0];p=__import__('pathlib').Path(grant.path);os.utime(p,(100,100))
 assert h.acquire(grant);assert h.cleanup(max_age_seconds=50,now=200)==() and p.exists()
 h.release(grant);assert h.cleanup(max_age_seconds=50,now=200)==(p.name,) and not p.exists()

def test_source_upload_never_gets_handoff_lease(tmp_path):
 root=tmp_path/'uploads';root.mkdir();p=root/'source';p.write_text('x');h=AttachmentHandoff(root,lambda *_:AttachmentRecord('f','u',str(p)))
 grant=h.resolve('u',['f'])[0];assert h.acquire(grant) is False
 assert not list(root.glob('*.lease'))

def test_stale_lease_recovery_uses_process_liveness(tmp_path):
 root=tmp_path/'uploads';root.mkdir();h=AttachmentHandoff(root,lambda *_:AttachmentRecord('f','u',text='x'))
 grant=h.resolve('u',['f'])[0];assert h.acquire(grant);lease=__import__('pathlib').Path(grant.path+'.lease')
 pid=int(lease.read_text().splitlines()[0]);assert pid>0
 assert h.recover_stale_leases(pid_alive=lambda candidate:candidate==pid)==()
 assert lease.exists()
 assert h.recover_stale_leases(pid_alive=lambda _:False)==(lease.name,) and not lease.exists()

def test_malformed_lease_fails_closed(tmp_path):
 root=tmp_path/'uploads';root.mkdir();h=AttachmentHandoff(root,lambda *_:None);h.handoff_root.mkdir()
 lease=h.handoff_root/'x.txt.lease';lease.write_text('not-a-pid')
 assert h.recover_stale_leases(pid_alive=lambda _:False)==() and lease.exists()

def test_cleanup_loop_recovers_stale_before_expiry(tmp_path):
 import os
 from ai_foundation.attachment_handoff import AttachmentCleanupLoop
 root=tmp_path/'uploads';root.mkdir();h=AttachmentHandoff(root,lambda *_:AttachmentRecord('f','u',text='x'))
 grant=h.resolve('u',['f'])[0];p=__import__('pathlib').Path(grant.path);os.utime(p,(100,100));h.acquire(grant)
 # Make the lease well-formed but dead; tick must recover it before cleanup.
 p.with_suffix(p.suffix+'.lease').write_text('999999999\n1\n')
 loop=AttachmentCleanupLoop(h,max_age_seconds=1);removed=loop.tick()
 assert removed==(p.name,) and not p.exists()

def test_failed_materialization_removes_partial_tmp(tmp_path,monkeypatch):
 root=tmp_path/'uploads';root.mkdir();h=AttachmentHandoff(root,lambda *_:AttachmentRecord('f','u',text='x'))
 original=__import__('pathlib').Path.chmod
 def fail_chmod(self,mode):
  if self.name.endswith('.tmp'): raise OSError('simulated chmod failure')
  return original(self,mode)
 monkeypatch.setattr(__import__('pathlib').Path,'chmod',fail_chmod)
 with pytest.raises(OSError):h.resolve('u',['f'])
 assert not list(h.handoff_root.glob('*.tmp')) and not list(h.handoff_root.glob('*.txt'))

def test_startup_recovery_removes_abandoned_tmp_only(tmp_path):
 root=tmp_path/'uploads';root.mkdir();h=AttachmentHandoff(root,lambda *_:None);h.handoff_root.mkdir()
 tmp=h.handoff_root/'abandoned.txt.tmp';tmp.write_text('partial');keep=h.handoff_root/'keep.txt';keep.write_text('complete')
 removed=h.recover_stale_leases(pid_alive=lambda _:True)
 assert removed==(tmp.name,) and not tmp.exists() and keep.exists()

def test_upstream_deleted_record_removes_inactive_derived_copy(tmp_path):
 root=tmp_path/'uploads';root.mkdir();records={('f','u'):AttachmentRecord('f','u',text='x')};h=AttachmentHandoff(root,lambda aid,owner:records.get((aid,owner)))
 grant=h.resolve('u',['f'])[0];p=__import__('pathlib').Path(grant.path);meta=p.with_suffix('.meta');assert p.exists() and meta.exists()
 records.clear();assert h.reconcile_upstream()==(p.name,);assert not p.exists() and not meta.exists()

def test_upstream_deleted_record_preserves_active_derived_copy(tmp_path):
 root=tmp_path/'uploads';root.mkdir();records={('f','u'):AttachmentRecord('f','u',text='x')};h=AttachmentHandoff(root,lambda aid,owner:records.get((aid,owner)))
 grant=h.resolve('u',['f'])[0];p=__import__('pathlib').Path(grant.path);h.acquire(grant);records.clear()
 assert h.reconcile_upstream()==() and p.exists();h.release(grant);assert h.reconcile_upstream()==(p.name,)

def test_materialization_enospc_is_atomic_and_recovers_on_retry(tmp_path,monkeypatch):
 import errno
 root=tmp_path/'uploads';root.mkdir();record=AttachmentRecord('f','u',text='complete')
 h=AttachmentHandoff(root,lambda *_:record)
 original=__import__('pathlib').Path.write_text; failed={'done':False}
 def enospc_once(self,data,*args,**kwargs):
  if self.name.endswith('.tmp') and not failed['done']:
   failed['done']=True
   raise OSError(errno.ENOSPC,'simulated inode/storage exhaustion')
  return original(self,data,*args,**kwargs)
 monkeypatch.setattr(__import__('pathlib').Path,'write_text',enospc_once)
 with pytest.raises(OSError) as exc:h.resolve('u',['f'])
 assert exc.value.errno==errno.ENOSPC
 assert h.handoff_root.exists() and not list(h.handoff_root.iterdir())
 grant=h.resolve('u',['f'])[0];p=__import__('pathlib').Path(grant.path)
 assert p.read_text()=='complete' and p.with_suffix('.meta').exists() and not list(h.handoff_root.glob('*.tmp'))

def test_cleanup_large_fanout_preserves_active_and_source_authority(tmp_path):
 import os
 root=tmp_path/'uploads';root.mkdir();d=root/'.foundation-handoff';d.mkdir();source=root/'source.txt';source.write_text('authority')
 h=AttachmentHandoff(root,lambda *_:None)
 for i in range(10_000):
  p=d/f'{i:05d}.txt';p.write_text('x');os.utime(p,(100,100))
 protected=d/'protected.txt';protected.write_text('x');os.utime(protected,(100,100));protected.with_suffix('.txt.lease').write_text(f'{os.getpid()}\n1\n')
 removed=h.cleanup(max_age_seconds=1,now=200)
 assert len(removed)==10_000 and protected.exists() and source.read_text()=='authority'
 assert {p.name for p in d.iterdir()}=={'protected.txt','protected.txt.lease'}

def test_metadata_creation_enospc_never_publishes_partial_handoff(tmp_path,monkeypatch):
 import errno
 root=tmp_path/'uploads';root.mkdir();h=AttachmentHandoff(root,lambda *_:AttachmentRecord('f','u',text='complete'))
 original=__import__('pathlib').Path.write_text
 def fail_meta_tmp(self,data,*args,**kwargs):
  if self.name.endswith('.meta.tmp'):raise OSError(errno.ENOSPC,'simulated inode exhaustion')
  return original(self,data,*args,**kwargs)
 monkeypatch.setattr(__import__('pathlib').Path,'write_text',fail_meta_tmp)
 with pytest.raises(OSError) as exc:h.resolve('u',['f'])
 assert exc.value.errno==errno.ENOSPC
 assert h.handoff_root.exists() and not list(h.handoff_root.iterdir())

def test_rejects_symlink_attachment_before_resolution(tmp_path):
    root=tmp_path/"uploads";root.mkdir()
    real=root/"real.png";real.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    link=root/"link.png";link.symlink_to(real)

    h=AttachmentHandoff(
        root,
        lambda attachment_id,owner_id:
            AttachmentRecord(attachment_id,owner_id,str(link)),
    )

    with pytest.raises(PermissionError,match="symlink"):
        h.resolve("owner",("img",))
