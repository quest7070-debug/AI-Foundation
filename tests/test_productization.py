import json
import sqlite3
import pytest
from ai_foundation.productization import FoundationConfig,backup,load_config,platform_capabilities,restore,save_config

def config(tmp_path): return FoundationConfig(str((tmp_path/'data').resolve()))

def test_config_roundtrip_and_path_confinement(tmp_path):
    c=config(tmp_path); p=tmp_path/'config.json'; save_config(c,p); assert load_config(p)==c
    with pytest.raises(ValueError): FoundationConfig('relative').validate()
    with pytest.raises(ValueError): FoundationConfig(str(tmp_path.resolve()),guard_db='../escape.db').validate()
    bad=json.loads(p.read_text()); bad['schema_version']=999; p.write_text(json.dumps(bad))
    with pytest.raises(ValueError,match='schema'): load_config(p)

def test_backup_restore_integrity_sqlite_and_trace(tmp_path):
    c=config(tmp_path); root=__import__('pathlib').Path(c.data_dir); root.mkdir()
    with sqlite3.connect(root/c.guard_db) as db: db.execute('create table x(v text)'); db.execute('insert into x values (?)',('日本語🔐',))
    with sqlite3.connect(root/c.work_db) as db: db.execute('create table y(v int)'); db.execute('insert into y values (42)')
    (root/c.trace_file).write_text('trace\n',encoding='utf-8')
    manifest=backup(c,tmp_path/'backup'); restored=tmp_path/'restored'; files=restore(tmp_path/'backup',restored)
    assert set(files)=={c.guard_db,c.work_db,c.trace_file,'config.json'} and len(manifest['files'])==4
    assert load_config(restored/'config.json')==c
    with sqlite3.connect(restored/c.guard_db) as db: assert db.execute('select v from x').fetchone()[0]=='日本語🔐'
    assert (restored/c.trace_file).read_text()=='trace\n'

def test_tampered_backup_fails_before_restore(tmp_path):
    c=config(tmp_path); root=__import__('pathlib').Path(c.data_dir); root.mkdir(); (root/c.trace_file).write_text('ok')
    backup(c,tmp_path/'backup'); (tmp_path/'backup'/c.trace_file).write_text('tampered')
    with pytest.raises(ValueError,match='integrity'): restore(tmp_path/'backup',tmp_path/'restored')
    assert not (tmp_path/'restored').exists()

def test_platform_capability_is_explicit():
    c=platform_capabilities(); assert {'system','machine','native_secret_store','toolhive_supported'}==set(c)

def test_backup_uses_consistent_sqlite_for_all_foundation_databases(tmp_path):
 from ai_foundation.productization import FoundationConfig,backup,restore
 import sqlite3
 root=tmp_path/'live';root.mkdir();c=FoundationConfig(str(root))
 for name in (c.guard_db,c.work_db,c.provider_db,c.routing_db,c.reconciliation_db):
  with sqlite3.connect(root/name) as d:d.execute('create table x(v)');d.execute('insert into x values(1)')
 b=tmp_path/'backup';m=backup(c,b);assert all(name in m['files'] for name in (c.provider_db,c.routing_db,c.reconciliation_db))
 out=tmp_path/'out';restore(b,out)
 for name in (c.provider_db,c.routing_db,c.reconciliation_db):
  with sqlite3.connect(out/name) as d:assert d.execute('select v from x').fetchone()==(1,)

def test_backup_includes_presentation_preference_when_present(tmp_path):
 c=config(tmp_path);root=__import__('pathlib').Path(c.data_dir);root.mkdir();(root/'presentation.json').write_text('{"theme":"C"}')
 m=backup(c,tmp_path/'backup');assert 'presentation.json' in m['files']
 restore(tmp_path/'backup',tmp_path/'out');assert (tmp_path/'out'/'presentation.json').read_text()=='{"theme":"C"}'

def test_backup_manifest_declares_cross_store_capture_semantics(tmp_path):
 c=config(tmp_path);__import__('pathlib').Path(c.data_dir).mkdir();m=backup(c,tmp_path/'b')
 assert m['capture']['consistency']=='per-file-snapshot' and m['capture']['started_ns']<=m['capture']['ended_ns']
 assert json.loads((tmp_path/'b'/'manifest.json').read_text())['capture']==m['capture']

def test_clean_disaster_restore_can_relocate_config_without_changing_rollback_default(tmp_path):
 c=config(tmp_path);root=__import__('pathlib').Path(c.data_dir);root.mkdir();(root/c.trace_file).write_text('x');backup(c,tmp_path/'b')
 out=tmp_path/'clean-host';restore(tmp_path/'b',out,relocate_config=True);assert load_config(out/'config.json').data_dir==str(out.resolve())
