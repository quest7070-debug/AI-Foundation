import json
import pytest
from pathlib import Path
from ai_foundation.productization import FoundationConfig,backup,restore,load_config,sha256

def cfg(tmp_path):return FoundationConfig(str((tmp_path/'data').resolve()))
def test_backup_contains_valid_config_and_refuses_overwrite(tmp_path):
    c=cfg(tmp_path);Path(c.data_dir).mkdir();b=tmp_path/'backup';m=backup(c,b)
    assert 'config.json' in m['files'];assert sha256(b/'config.json')==m['files']['config.json'];assert load_config(b/'config.json')==c
    with pytest.raises(FileExistsError):backup(c,b)
def test_restore_refuses_existing_destination_without_mutation(tmp_path):
    c=cfg(tmp_path);root=Path(c.data_dir);root.mkdir();(root/c.trace_file).write_text('new');b=tmp_path/'backup';backup(c,b)
    dest=tmp_path/'restored';dest.mkdir();marker=dest/'keep';marker.write_text('old')
    with pytest.raises(FileExistsError):restore(b,dest)
    assert marker.read_text()=='old';assert list(dest.iterdir())==[marker]
def test_restore_copy_failure_leaves_no_destination(tmp_path,monkeypatch):
    c=cfg(tmp_path);root=Path(c.data_dir);root.mkdir();(root/c.trace_file).write_text('trace');b=tmp_path/'backup';backup(c,b);dest=tmp_path/'restored'
    import ai_foundation.productization as p
    real=p.shutil.copy2;calls={'n':0}
    def fail_second(src,dst,*a,**k):
        calls['n']+=1
        if calls['n']==2:raise OSError('simulated disk failure')
        return real(src,dst,*a,**k)
    monkeypatch.setattr(p.shutil,'copy2',fail_second)
    with pytest.raises(OSError):restore(b,dest)
    assert not dest.exists();assert not list(tmp_path.glob('.restored.staging-*'))
def test_backup_publish_failure_leaves_no_destination(tmp_path,monkeypatch):
    c=cfg(tmp_path);root=Path(c.data_dir);root.mkdir();(root/c.trace_file).write_text('trace');dest=tmp_path/'backup'
    import ai_foundation.productization as p
    monkeypatch.setattr(p,'_publish_dir',lambda stage,dest:(_ for _ in ()).throw(OSError('publish failed')))
    with pytest.raises(OSError):backup(c,dest)
    assert not dest.exists();assert not list(tmp_path.glob('.backup.staging-*'))

def test_trace_append_during_backup_yields_self_consistent_snapshot(tmp_path,monkeypatch):
    c=cfg(tmp_path);root=Path(c.data_dir);root.mkdir();trace=root/c.trace_file;trace.write_text('before\n');dest=tmp_path/'backup'
    import ai_foundation.productization as p
    real=p.shutil.copy2
    def append_then_copy(src,dst,*a,**k):
        if Path(src)==trace:
            with trace.open('a',encoding='utf-8') as f:f.write('during\n')
        return real(src,dst,*a,**k)
    monkeypatch.setattr(p.shutil,'copy2',append_then_copy)
    manifest=backup(c,dest)
    assert sha256(dest/c.trace_file)==manifest['files'][c.trace_file]
    assert (dest/c.trace_file).read_text(encoding='utf-8') in {'before\n','before\nduring\n'}

def test_backup_db_is_sqlite_consistent_while_source_open(tmp_path):
    import sqlite3
    c=cfg(tmp_path);root=Path(c.data_dir);root.mkdir();dbpath=root/c.guard_db
    writer=sqlite3.connect(dbpath);writer.execute('create table x(v int)');writer.execute('insert into x values (1)');writer.commit();writer.execute('insert into x values (2)')
    b=tmp_path/'backup';backup(c,b);writer.rollback();writer.close()
    with sqlite3.connect(b/c.guard_db) as db: assert db.execute('pragma integrity_check').fetchone()[0]=='ok' and db.execute('select v from x').fetchall()==[(1,)]

def test_restore_rejects_tampered_config_before_publish(tmp_path):
    c=cfg(tmp_path);Path(c.data_dir).mkdir();b=tmp_path/'backup';backup(c,b);(b/'config.json').write_text('{}')
    dest=tmp_path/'restored'
    with pytest.raises(ValueError,match='integrity'):restore(b,dest)
    assert not dest.exists()

def test_restore_rejects_manifest_path_traversal(tmp_path):
 import json
 from ai_foundation.productization import restore
 b=tmp_path/'b';b.mkdir();(b/'manifest.json').write_text(json.dumps({'schema_version':1,'files':{'../escape':'x'}}))
 import pytest
 with pytest.raises(ValueError,match='unsafe'):restore(b,tmp_path/'out')
