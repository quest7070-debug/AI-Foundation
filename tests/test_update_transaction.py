import json
from pathlib import Path
import pytest
from ai_foundation.migration import verify_update_package,apply_update_transaction
from ai_foundation.productization import FoundationConfig,sha256

def cfg(tmp_path):return FoundationConfig(str((tmp_path/'live').resolve()))
def package(tmp_path):
    p=tmp_path/'pkg';p.mkdir();(p/'payload.txt').write_text('v-next');(p/'update-manifest.json').write_text(json.dumps({'schema_version':1,'files':{'payload.txt':sha256(p/'payload.txt')}}));return p
def test_update_package_integrity_and_path_confinement(tmp_path):
    p=package(tmp_path);assert verify_update_package(p)['schema_version']==1
    (p/'payload.txt').write_text('tampered')
    with pytest.raises(ValueError,match='integrity'):verify_update_package(p)
    (p/'update-manifest.json').write_text(json.dumps({'schema_version':1,'files':{'../escape':'x'}}))
    with pytest.raises(ValueError,match='path'):verify_update_package(p)
def test_verified_update_takes_backup_before_apply(tmp_path):
    c=cfg(tmp_path);live=Path(c.data_dir);live.mkdir();(live/'trace.jsonl').write_text('old');p=package(tmp_path);seen=[]
    def apply(pkg):seen.append((tmp_path/'backup').exists());(live/'marker').write_text((pkg/'payload.txt').read_text())
    result=apply_update_transaction(c,p,tmp_path/'backup',apply,lambda:(live/'marker').read_text()=='v-next',tmp_path/'rollback')
    assert result.status=='VERIFIED' and result.applied and seen==[True];assert (tmp_path/'backup'/'trace.jsonl').read_text()=='old'
def test_failed_readback_restores_preupdate_state(tmp_path):
    c=cfg(tmp_path);live=Path(c.data_dir);live.mkdir();(live/'trace.jsonl').write_text('old');p=package(tmp_path)
    def apply(pkg):(live/'trace.jsonl').write_text('new');(live/'bad').write_text('partial')
    with pytest.raises(RuntimeError,match='readback'):apply_update_transaction(c,p,tmp_path/'backup',apply,lambda:False,tmp_path/'rollback')
    assert (live/'trace.jsonl').read_text()=='old';assert not (live/'bad').exists();assert (live/'config.json').exists()
def test_apply_exception_rolls_back(tmp_path):
    c=cfg(tmp_path);live=Path(c.data_dir);live.mkdir();(live/'trace.jsonl').write_text('old');p=package(tmp_path)
    def apply(pkg):(live/'trace.jsonl').write_text('new');raise OSError('apply failed')
    with pytest.raises(OSError,match='apply failed'):apply_update_transaction(c,p,tmp_path/'backup',apply,lambda:True,tmp_path/'rollback')
    assert (live/'trace.jsonl').read_text()=='old'

def test_rollback_failure_preserves_backup_and_failed_live(tmp_path,monkeypatch):
    from ai_foundation.migration import UpdateRollbackError
    import ai_foundation.migration as m
    c=cfg(tmp_path);live=Path(c.data_dir);live.mkdir();(live/'trace.jsonl').write_text('old');p=package(tmp_path)
    def apply(pkg):(live/'trace.jsonl').write_text('new');(live/'partial').write_text('keep-for-forensics')
    real_restore=m.restore
    def fail_restore(*a,**k):raise OSError('simulated restore failure')
    monkeypatch.setattr(m,'restore',fail_restore)
    with pytest.raises(UpdateRollbackError,match='rollback failed'):
        apply_update_transaction(c,p,tmp_path/'backup',apply,lambda:False,tmp_path/'rollback')
    assert (tmp_path/'backup'/'trace.jsonl').read_text()=='old'
    quarantine=tmp_path/'.live.failed-update'
    assert (quarantine/'trace.jsonl').read_text()=='new'
    assert (quarantine/'partial').read_text()=='keep-for-forensics'
    assert not live.exists()

def test_preexisting_quarantine_fails_closed_and_preserves_it(tmp_path):
    from ai_foundation.migration import UpdateRollbackError
    c=cfg(tmp_path);live=Path(c.data_dir);live.mkdir();(live/'trace.jsonl').write_text('old');p=package(tmp_path);q=tmp_path/'.live.failed-update';q.mkdir();(q/'evidence').write_text('older incident')
    def apply(pkg):(live/'trace.jsonl').write_text('new')
    with pytest.raises(UpdateRollbackError,match='quarantine already exists'):
        apply_update_transaction(c,p,tmp_path/'backup',apply,lambda:False,tmp_path/'rollback')
    assert (q/'evidence').read_text()=='older incident'
    assert (live/'trace.jsonl').read_text()=='new'
    assert (tmp_path/'backup'/'trace.jsonl').read_text()=='old'

def test_update_journal_records_verified_transaction(tmp_path):
 from ai_foundation.migration import read_update_journal
 c=FoundationConfig(str((tmp_path/'livej').resolve()));live=Path(c.data_dir);live.mkdir();(live/c.trace_file).write_text('x')
 p=tmp_path/'pkgj';p.mkdir();(p/'x').write_text('x');(p/'update-manifest.json').write_text(json.dumps({'schema_version':1,'files':{'x':sha256(p/'x')}}))
 apply_update_transaction(c,p,tmp_path/'backupj',lambda _p:None,lambda:True,tmp_path/'rollbackj')
 assert read_update_journal(c)['status']=='VERIFIED'

def test_corrupt_update_journal_fails_closed(tmp_path):
 from ai_foundation.migration import read_update_journal,UpdateRollbackError,_journal_path
 c=cfg(tmp_path);p=_journal_path(c);p.write_text('{broken')
 with pytest.raises(UpdateRollbackError,match='journal unreadable'):read_update_journal(c)

def test_failed_update_backup_can_be_protected_as_lkg_during_generation_cleanup(tmp_path):
 from ai_foundation.storage_lifecycle import backup_series_plan,apply_owned_directory_plan,validate_backup_generation
 import os
 parent=tmp_path/'backups';parent.mkdir();c=cfg(tmp_path);live=Path(c.data_dir);live.mkdir();(live/'trace.jsonl').write_text('known-good');p=package(tmp_path)
 # Create older valid generations through the real backup path.
 from ai_foundation.productization import backup
 generations=[]
 for i in range(4):
  b=parent/f'foundation-backup-{i}';backup(c,b);os.utime(b,ns=(i,i));generations.append(b)
 failed_lkg=parent/'foundation-backup-failed-update'
 def apply(_pkg):(live/'trace.jsonl').write_text('bad')
 with pytest.raises(RuntimeError,match='readback'):
  apply_update_transaction(c,p,failed_lkg,apply,lambda:False,tmp_path/'rollback')
 assert (live/'trace.jsonl').read_text()=='known-good' and validate_backup_generation(failed_lkg)
 os.utime(failed_lkg,ns=(0,0)) # prove protection is semantic, not recency.
 plan=backup_series_plan(parent,'foundation-backup-',keep=3,protected=(failed_lkg,))
 assert failed_lkg not in plan
 apply_owned_directory_plan(plan,parent)
 assert failed_lkg.exists() and validate_backup_generation(failed_lkg)
 assert backup_series_plan(parent,'foundation-backup-',keep=3,protected=(failed_lkg,))==()
