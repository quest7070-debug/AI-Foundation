from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time
import subprocess
import sys
import pytest
import multiprocessing

from ai_foundation.capability_request import CapabilityRequest
from ai_foundation.files_adapter import build_files
from ai_foundation.guard import GuardCore
from ai_foundation.reconciliation_registry import SQLiteReconciliationRegistry
from ai_foundation.store import SQLiteGuardStore


class ConcurrentDiskPort:
    def __init__(self):
        self.writes = 0
        self.lock = threading.Lock()

    def execute(self, plan):
        with self.lock:
            self.writes += 1
        Path(plan.target).write_text(plan.text, encoding='utf-8')
        time.sleep(.02)

    def observe(self, plan):
        return Path(plan.target).read_text(encoding='utf-8')


def concurrent_produce(tmp_path, contents):
    output = tmp_path / 'out'
    output.mkdir()
    database = tmp_path / 'guard.sqlite3'
    recipes = tmp_path / 'recipes.sqlite3'
    SQLiteGuardStore(database)
    registry = SQLiteReconciliationRegistry(recipes)
    port = ConcurrentDiskPort()
    start = threading.Barrier(len(contents))

    def worker(content):
        store = SQLiteGuardStore(database)
        files = build_files(CapabilityRequest('FILES', owner_id='owner',
            file_read_root=str(output), file_write_root=str(output)),
            GuardCore(store.runtime_state(), store=store), port,
            reconciliation_registry=registry, port_binding='disk')
        start.wait(timeout=10)
        return content, files.produce_text_artifact('shared-run', 'report.txt', content)

    with ThreadPoolExecutor(max_workers=len(contents)) as pool:
        results = list(pool.map(worker, contents))
    return output, SQLiteGuardStore(database), registry, port, results


def test_concurrent_same_effect_writes_once_and_every_reader_verifies(tmp_path):
    output, store, registry, port, results = concurrent_produce(tmp_path, ['same'] * 8)
    assert port.writes == 1
    assert [r.status for _, r in results] == ['VERIFIED_COMPLETE'] * 8
    effect = next(iter(store.load().effects.values()))
    assert effect.expected == registry.load(effect.effect_id)[0].text == (output / 'report.txt').read_text()


def test_concurrent_conflicting_contents_cannot_replace_winning_effect_or_recipe(tmp_path):
    output, store, registry, port, results = concurrent_produce(tmp_path, [f'content-{i}' for i in range(8)])
    winners = [(content, result) for content, result in results if result.verified]
    assert len(winners) == 1 and port.writes == 1
    assert all(result.status == 'ARTIFACT_IDENTITY_CONFLICT' for content, result in results if content != winners[0][0])
    effect = next(iter(store.load().effects.values()))
    assert effect.expected == registry.load(effect.effect_id)[0].text == winners[0][0]
    assert (output / 'report.txt').read_text() == winners[0][0]


def test_cached_planned_effect_uses_current_durable_state_after_other_writer_completes(tmp_path):
    from ai_foundation.core import EffectIntent
    from hashlib import sha256
    output = tmp_path / 'out'
    output.mkdir()
    target = str((output / 'report.txt').resolve())
    identity = 'shared-run:text-artifact:' + sha256(target.encode()).hexdigest()
    store = SQLiteGuardStore(tmp_path / 'guard.sqlite3')
    state = store.runtime_state()
    state.effects[identity] = EffectIntent(identity, 'shared-run', target, 'same')
    store.save(state)
    request = CapabilityRequest('FILES', owner_id='owner', file_read_root=str(output), file_write_root=str(output))
    port = ConcurrentDiskPort()
    writers = [build_files(request, GuardCore(store.load(), store=store), port) for _ in range(2)]
    assert writers[0].produce_text_artifact('shared-run', 'report.txt', 'same').verified
    assert writers[1].produce_text_artifact('shared-run', 'report.txt', 'same').verified
    assert port.writes == 1


def test_killed_writer_releases_kernel_lock_and_recovery_observes_without_rewrite(tmp_path):
    output = tmp_path / 'out'
    output.mkdir()
    database = tmp_path / 'guard.sqlite3'
    recipes = tmp_path / 'recipes.sqlite3'
    SQLiteGuardStore(database)
    SQLiteReconciliationRegistry(recipes)
    script = '''
import os, sys
sys.path.insert(0, sys.argv[4])
from pathlib import Path
from ai_foundation.capability_request import CapabilityRequest
from ai_foundation.files_adapter import build_files
from ai_foundation.guard import GuardCore
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.reconciliation_registry import SQLiteReconciliationRegistry
root, database, recipes = sys.argv[1:4]
class CrashPort:
    def execute(self, plan):
        Path(plan.target).write_text(plan.text, encoding='utf-8')
        os._exit(23)
    def observe(self, plan): return Path(plan.target).read_text(encoding='utf-8')
store = SQLiteGuardStore(database)
files = build_files(CapabilityRequest('FILES', owner_id='owner', file_read_root=root, file_write_root=root),
    GuardCore(store.runtime_state(), store=store, claim_ttl=.03), CrashPort(),
    reconciliation_registry=SQLiteReconciliationRegistry(recipes), port_binding='disk')
files.produce_text_artifact('crash-run', 'report.txt', 'written-before-exit')
'''
    child = subprocess.run([sys.executable, '-c', script, str(output), str(database), str(recipes),
        str(Path(__file__).resolve().parents[1] / 'src')],
        capture_output=True, timeout=10)
    assert child.returncode == 23, child.stderr.decode()
    port = ConcurrentDiskPort()
    reopened = SQLiteGuardStore(database)
    files = build_files(CapabilityRequest('FILES', owner_id='owner', file_read_root=str(output), file_write_root=str(output)),
        GuardCore(reopened.runtime_state(), store=reopened), port,
        reconciliation_registry=SQLiteReconciliationRegistry(recipes), port_binding='disk')
    deadline = time.monotonic() + 3
    while True:
        result = files.produce_text_artifact('crash-run', 'report.txt', 'written-before-exit')
        if result.status != 'EFFECT_IN_PROGRESS' or time.monotonic() >= deadline:
            break
        time.sleep(.03)
    assert result.verified and port.writes == 0
    assert (output / 'report.txt').read_text() == 'written-before-exit'


def test_artifact_lock_inode_is_retained_and_symlink_is_refused(tmp_path):
    root = tmp_path / 'out'
    root.mkdir()
    port = ConcurrentDiskPort()
    files = build_files(CapabilityRequest('FILES', owner_id='owner', file_read_root=str(root), file_write_root=str(root)),
        GuardCore(SQLiteGuardStore(tmp_path / 'guard.sqlite3').runtime_state()), port)
    assert files.produce_text_artifact('run', 'report.txt', 'same').verified
    lock = next(root.glob('.foundation-text-artifact-*.lock'))
    inode = lock.stat().st_ino
    assert files.produce_text_artifact('run', 'report.txt', 'same').verified
    assert lock.stat().st_ino == inode
    lock.unlink()
    outside = tmp_path / 'outside'
    outside.write_text('unchanged')
    lock.symlink_to(outside)
    with pytest.raises(OSError):
        files.produce_text_artifact('other-run', 'report.txt', 'text')
    assert outside.read_text() == 'unchanged' and (root / 'report.txt').read_text() == 'same'


def test_independent_targets_are_not_serialized_by_the_artifact_lock(tmp_path):
    root = tmp_path / 'out'
    root.mkdir()
    barrier = threading.Barrier(2)
    class IndependentPort(ConcurrentDiskPort):
        def execute(self, plan):
            barrier.wait(timeout=5)
            super().execute(plan)
    port = IndependentPort()
    def worker(name):
        files = build_files(CapabilityRequest('FILES', owner_id='owner',
            file_read_root=str(root), file_write_root=str(root)), GuardCore(SQLiteGuardStore(tmp_path / (name + '.sqlite3')).runtime_state()), port)
        return files.produce_text_artifact('run', name + '.txt', name)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ['first', 'second']))
    assert all(result.verified for result in results) and port.writes == 2


def test_overlapping_host_scopes_use_the_same_normalized_target_lock(tmp_path):
    root = tmp_path / 'out'
    nested = root / 'nested'
    nested.mkdir(parents=True)
    store = SQLiteGuardStore(tmp_path / 'guard.sqlite3')
    registry = SQLiteReconciliationRegistry(tmp_path / 'recipes.sqlite3')
    port = ConcurrentDiskPort()
    start = threading.Barrier(2)
    def worker(scope):
        files = build_files(CapabilityRequest('FILES', owner_id='owner',
            file_read_root=str(scope), file_write_root=str(scope)),
            GuardCore(store.runtime_state(), store=store), port,
            reconciliation_registry=registry, port_binding='disk')
        start.wait(timeout=5)
        return files.produce_text_artifact('run', str(nested / 'report.txt'), 'same')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, [root, nested]))
    assert all(result.verified for result in results) and port.writes == 1


def test_protected_nested_target_creates_no_lock_metadata(tmp_path):
    from ai_foundation.protected_resources import ProtectedResources
    protected = tmp_path / 'protected'
    protected.mkdir()
    files = build_files(CapabilityRequest('FILES', owner_id='owner',
        file_read_root=str(tmp_path), file_write_root=str(tmp_path)), GuardCore(SQLiteGuardStore(tmp_path / 'guard.sqlite3').runtime_state()),
        ConcurrentDiskPort(), protected=ProtectedResources((str(protected),)))
    with pytest.raises(PermissionError):
        files.produce_text_artifact('run', 'protected/report.txt', 'text')
    assert list(protected.iterdir()) == []


def test_read_only_execution_cannot_create_artifact_lock_metadata(tmp_path):
    from ai_foundation.artifact import produce_text_artifact
    from ai_foundation.file_execution import ScopedFileExecution, FileScope
    execution = ScopedFileExecution(GuardCore(SQLiteGuardStore(tmp_path / 'guard.sqlite3').runtime_state()),
        ConcurrentDiskPort(), FileScope(str(tmp_path), write=False))
    with pytest.raises(PermissionError):
        produce_text_artifact(execution, 'run', 'report.txt', 'text')
    assert not list(tmp_path.glob('.foundation-text-artifact-*.lock'))


def _process_writer(output, database, recipes, start, results):
    store = SQLiteGuardStore(database)
    port = ConcurrentDiskPort()
    files = build_files(CapabilityRequest('FILES', owner_id='owner',
        file_read_root=output, file_write_root=output),
        GuardCore(store.runtime_state(), store=store), port,
        reconciliation_registry=SQLiteReconciliationRegistry(recipes), port_binding='disk')
    results.put('ready')
    if not start.wait(10):
        raise RuntimeError('test start deadline expired')
    result = files.produce_text_artifact('process-run', 'report.txt', 'same')
    results.put((result.status, port.writes))


def test_separate_processes_share_one_write_and_one_durable_recipe(tmp_path):
    output = tmp_path / 'out'
    output.mkdir()
    database = tmp_path / 'guard.sqlite3'
    recipes = tmp_path / 'recipes.sqlite3'
    SQLiteGuardStore(database)
    SQLiteReconciliationRegistry(recipes)
    context = multiprocessing.get_context('spawn')
    start, results = context.Event(), context.Queue()
    processes = [context.Process(target=_process_writer,
        args=(str(output), str(database), str(recipes), start, results)) for _ in range(3)]
    try:
        for process in processes:
            process.start()
        assert [results.get(timeout=10) for _ in processes] == ['ready'] * 3
        start.set()
        observed = [results.get(timeout=10) for _ in processes]
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
        assert [status for status, _ in observed] == ['VERIFIED_COMPLETE'] * 3
        assert sum(writes for _, writes in observed) == 1
        effect = next(iter(SQLiteGuardStore(database).load().effects.values()))
        assert effect.expected == SQLiteReconciliationRegistry(recipes).load(effect.effect_id)[0].text == 'same'
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            if process.pid is not None:
                process.join(timeout=5)
        results.close()
