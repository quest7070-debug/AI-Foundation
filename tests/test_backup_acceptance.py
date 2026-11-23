import json
import os
from pathlib import Path
import sqlite3

import pytest

from ai_foundation.productization import FoundationConfig, backup, restore, sha256
from ai_foundation.storage_lifecycle import validate_backup_generation, backup_retention_plan


def make_backup(tmp_path, name='backup'):
    source = tmp_path / (name + '-live')
    source.mkdir()
    config = FoundationConfig(str(source))
    with sqlite3.connect(source / config.guard_db) as db:
        db.execute('CREATE TABLE sample(value TEXT)')
        db.execute('INSERT INTO sample VALUES (?)', ('検証済み',))
    destination = tmp_path / name
    backup(config, destination)
    return config, destination


def change_manifest(directory, edit):
    path = directory / 'manifest.json'
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data), encoding='utf-8')


def test_configured_database_with_nonstandard_extension_preserves_committed_wal(tmp_path):
    source = tmp_path / 'live'
    source.mkdir()
    config = FoundationConfig(str(source), guard_db='guard.data')
    writer = sqlite3.connect(source / config.guard_db)
    try:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('CREATE TABLE sample(value INTEGER)')
        writer.execute('INSERT INTO sample VALUES (1)')
        writer.commit()
        writer.execute('INSERT INTO sample VALUES (2)')
        writer.commit()
        writer.execute('INSERT INTO sample VALUES (3)')
        backup(config, tmp_path / 'backup')
        restore(tmp_path / 'backup', tmp_path / 'restored')
        with sqlite3.connect(tmp_path / 'restored' / config.guard_db) as db:
            assert db.execute('SELECT value FROM sample ORDER BY value').fetchall() == [(1,), (2,)]
        assert writer.in_transaction
    finally:
        writer.rollback()
        writer.close()


@pytest.mark.parametrize('schema', [999, True, '1'])
def test_unknown_or_wrongly_typed_schema_cannot_count_as_valid_generation(tmp_path, schema):
    _, directory = make_backup(tmp_path)
    change_manifest(directory, lambda m: m.update(schema_version=schema))
    assert validate_backup_generation(directory) is False


@pytest.mark.parametrize('planner', ['backup_retention_plan', 'backup_generation_plan', 'backup_series_plan'])
def test_matching_hashes_without_config_cannot_displace_last_restorable_generation(tmp_path, planner):
    _, good = make_backup(tmp_path, 'good')
    _, incomplete = make_backup(tmp_path, 'incomplete')
    change_manifest(incomplete, lambda m: m['files'].pop('config.json'))
    (incomplete / 'config.json').unlink()
    os.utime(good, (100, 100))
    os.utime(incomplete, (200, 200))
    from ai_foundation import storage_lifecycle
    plan = getattr(storage_lifecycle, planner)
    if planner == 'backup_series_plan':
        assert plan(tmp_path, '', keep=1) == ()
    else:
        assert plan([good, incomplete], keep=1) == ()
    assert good.exists() and incomplete.exists()


def test_corrupt_sqlite_with_matching_manifest_digest_is_not_restorable(tmp_path):
    config, directory = make_backup(tmp_path)
    (directory / config.guard_db).write_bytes(b'not a sqlite database')
    change_manifest(directory, lambda m: m['files'].update({config.guard_db: sha256(directory / config.guard_db)}))
    assert validate_backup_generation(directory) is False
    with pytest.raises(ValueError):
        restore(directory, tmp_path / 'must-not-exist')
    assert not (tmp_path / 'must-not-exist').exists()


def test_invalid_configuration_is_refused_even_when_hash_matches(tmp_path):
    _, directory = make_backup(tmp_path)
    (directory / 'config.json').write_text('{"data_dir":"relative"}')
    change_manifest(directory, lambda m: m['files'].update({'config.json': sha256(directory / 'config.json')}))
    with pytest.raises(ValueError):
        restore(directory, tmp_path / 'must-not-exist')
    assert not (tmp_path / 'must-not-exist').exists()


def test_duplicate_manifest_keys_fail_before_restore_destination_creation(tmp_path):
    _, directory = make_backup(tmp_path)
    original = (directory / 'manifest.json').read_text()
    (directory / 'manifest.json').write_text(original.replace('"schema_version": 1', '"schema_version": 999, "schema_version": 1'))
    with pytest.raises(ValueError):
        restore(directory, tmp_path / 'must-not-exist')
    assert not (tmp_path / 'must-not-exist').exists()


@pytest.mark.parametrize('keep', [0, -1, True, 1.5, '1'])
def test_generation_plans_refuse_configuration_that_can_remove_last_backup(tmp_path, keep):
    from ai_foundation.storage_lifecycle import backup_generation_plan, backup_series_plan, BackupMaintenance
    for operation in [lambda: backup_generation_plan([], keep), lambda: backup_retention_plan([], keep),
        lambda: backup_series_plan(tmp_path, 'backup-', keep), lambda: BackupMaintenance(tmp_path, keep=keep)]:
        with pytest.raises(ValueError, match='at least one'):
            operation()


@pytest.mark.parametrize('content', [None, [], {'schema_version': 1, 'files': []},
    {'schema_version': 1, 'files': {}}, {'schema_version': 1, 'files': {'config.json': 'invalid'}}])
def test_malformed_manifest_is_a_failed_generation_not_a_maintenance_crash(tmp_path, content):
    _, directory = make_backup(tmp_path)
    (directory / 'manifest.json').write_text(json.dumps(content))
    assert validate_backup_generation(directory) is False


def test_manifest_size_limit_is_checked_before_parsing(tmp_path):
    _, directory = make_backup(tmp_path)
    (directory / 'manifest.json').write_bytes(b' ' * (1024 * 1024 + 1))
    assert validate_backup_generation(directory) is False


@pytest.mark.parametrize('capture', [None, {},
    {'consistency': 'per-file-snapshot', 'started_ns': 1, 'ended_ns': None},
    {'consistency': 'per-file-snapshot', 'started_ns': 2, 'ended_ns': 1},
    {'consistency': 'global-transaction', 'started_ns': 1, 'ended_ns': 2}])
def test_present_capture_metadata_must_describe_a_finished_supported_snapshot(tmp_path, capture):
    _, directory = make_backup(tmp_path)
    change_manifest(directory, lambda manifest: manifest.update(capture=capture))
    assert validate_backup_generation(directory) is False


def test_legacy_v1_generation_without_capture_metadata_remains_supported(tmp_path):
    _, directory = make_backup(tmp_path)
    change_manifest(directory, lambda manifest: manifest.pop('capture'))
    assert validate_backup_generation(directory)


def test_symlinked_snapshot_file_is_not_followed(tmp_path):
    config, directory = make_backup(tmp_path)
    outside = tmp_path / 'outside.sqlite'
    (directory / config.guard_db).replace(outside)
    (directory / config.guard_db).symlink_to(outside)
    before = outside.read_bytes()
    assert validate_backup_generation(directory) is False
    assert outside.read_bytes() == before


def test_read_only_verification_streams_content_and_creates_no_sqlite_sidecars(tmp_path, monkeypatch):
    from ai_foundation.productization import verify_backup
    _, directory = make_backup(tmp_path)
    before = {p.relative_to(directory): (p.stat().st_mtime_ns, p.read_bytes()) for p in directory.rglob('*') if p.is_file()}
    with monkeypatch.context() as scoped:
        scoped.setattr(Path, 'read_bytes', lambda self: (_ for _ in ()).throw(AssertionError('unbounded file read')))
        verify_backup(directory)
    after = {p.relative_to(directory): (p.stat().st_mtime_ns, p.read_bytes()) for p in directory.rglob('*') if p.is_file()}
    assert after == before


def test_standalone_verifier_reports_safe_metadata_and_failure_exit_status(tmp_path):
    import subprocess
    import sys
    _, directory = make_backup(tmp_path)
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'verify_backup.py'
    launcher = 'import runpy,sys;sys.path.insert(0,sys.argv.pop(1));sys.argv.pop(0);runpy.run_path(sys.argv[0],run_name="__main__")'
    args = [sys.executable, '-c', launcher, str(script.parent.parent / 'src'), str(script), str(directory)]
    result = subprocess.run(args, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'status': 'CONTENT_VERIFIED', 'schema_version': 1, 'verified_files': 2}
    (directory / 'config.json').write_text('private-path-must-not-be-printed')
    result = subprocess.run(args, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert json.loads(result.stdout) == {'status': 'INVALID_BACKUP', 'reason': 'integrity'}
    assert 'private-path-must-not-be-printed' not in result.stdout + result.stderr
    assert str(directory) not in result.stdout + result.stderr


@pytest.mark.parametrize('lost_ack', [False, True])
def test_real_guard_and_work_restore_does_not_repeat_existing_effect(tmp_path, lost_ack):
    from ai_foundation.core import CanonContract, TaskPlan
    from ai_foundation.guard import GuardCore
    from ai_foundation.store import SQLiteGuardStore
    from ai_foundation.durable_work import SQLiteWorkStore, DurableWorkRunner
    from ai_foundation.orchestration import WorkStatus
    source = tmp_path / 'live'
    source.mkdir()
    config = FoundationConfig(str(source))
    store = SQLiteGuardStore(source / config.guard_db)
    class Port:
        writes = 0
        def execute(self, plan):
            self.writes += 1
            Path(plan.target).write_text(plan.text)
            if lost_ack:
                raise ConnectionError('lost after effect')
        def observe(self, plan): return Path(plan.target).read_text()
    port = Port()
    plan = TaskPlan('run', 'write', str(tmp_path / 'world.txt'), text='once', canon_revision='v1')
    canon = CanonContract('test', 'v1')
    original = GuardCore(store.runtime_state(), store=store).execute(plan, canon, port, 'once')
    assert original == ('UNCERTAIN_RECONCILE_REQUIRED' if lost_ack else 'VERIFIED_COMPLETE')
    work = SQLiteWorkStore(source / config.work_db)
    work.ensure('job', ['step'])
    work.set('job', 0, WorkStatus.RUNNING)
    backup(config, tmp_path / 'backup')
    restore(tmp_path / 'backup', tmp_path / 'restored', relocate_config=True)
    reopened = SQLiteGuardStore(tmp_path / 'restored' / config.guard_db)
    assert GuardCore(reopened.runtime_state(), store=reopened).execute(plan, canon, port, 'once') == 'VERIFIED_COMPLETE'
    assert port.writes == 1
    restored_work = SQLiteWorkStore(tmp_path / 'restored' / config.work_db)
    def never_replay(): raise AssertionError('running work must be reconciled first')
    assert DurableWorkRunner(restored_work).execute('job', [('step', never_replay)]) is WorkStatus.RUNNING
