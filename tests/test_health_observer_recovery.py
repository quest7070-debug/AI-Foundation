from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest

from ai_foundation.long_term_health import (
    LongTermHealth, LongTermSignal, LongTermHealthLoop, LongTermHealthEvidenceStore,
)


def healthy(now=100):
    return LongTermHealth(now, (LongTermSignal('disk', True, '1 bytes'),))


def test_check_failure_replaces_cached_success_and_next_observation_recovers(tmp_path):
    fail = [False]
    def check():
        if fail[0]: raise OSError('DO_NOT_RECORD_secret_or_path')
        return healthy()
    store = LongTermHealthEvidenceStore(tmp_path / 'health.json')
    loop = LongTermHealthLoop(check, clock=lambda: 100, evidence_store=store)
    assert loop.tick().ok and loop.ok()
    fail[0] = True
    result = loop.tick()
    assert not result.ok and not loop.ok()
    assert not store.load().ok
    assert 'DO_NOT_RECORD' not in repr(result) + store.path.read_text()
    fail[0] = False
    assert loop.tick().ok and loop.ok() and store.load().ok


def test_evidence_write_failure_is_not_a_healthy_observation(tmp_path, monkeypatch):
    store = LongTermHealthEvidenceStore(tmp_path / 'health.json')
    loop = LongTermHealthLoop(healthy, clock=lambda: 100, evidence_store=store)
    assert loop.tick().ok
    original = store.save
    monkeypatch.setattr(store, 'save', lambda _: (_ for _ in ()).throw(OSError('DO_NOT_RECORD_private_path')))
    result = loop.tick()
    assert not result.ok and not loop.ok()
    assert any(signal.name == 'health-evidence' and not signal.ok for signal in result.signals)
    assert 'DO_NOT_RECORD' not in repr(result)
    monkeypatch.setattr(store, 'save', original)
    assert loop.tick().ok and loop.ok()


@pytest.mark.parametrize('timestamp', [float('nan'), float('inf'), True, '100'])
def test_invalid_observation_timestamp_never_becomes_healthy(timestamp):
    loop = LongTermHealthLoop(lambda: healthy(timestamp), clock=lambda: 100)
    assert not loop.tick().ok
    assert not loop.ok()


@pytest.mark.parametrize('edit', [
    lambda d: d['signals'][0].update(ok='false'),
    lambda d: d.update(checked_at=float('nan')),
    lambda d: d.update(checked_at=True),
    lambda d: d.update(signals=[]),
    lambda d: d.update(ok=False),
])
def test_invalid_persisted_health_does_not_become_success(tmp_path, edit):
    path = tmp_path / 'health.json'
    data = {'checked_at': 100, 'ok': True, 'signals': [{'name': 'disk', 'ok': True, 'detail': '1 bytes'}]}
    edit(data)
    path.write_text(json.dumps(data))
    assert LongTermHealthEvidenceStore(path).load() is None


def test_duplicate_json_fields_are_not_health_evidence(tmp_path):
    path = tmp_path / 'health.json'
    path.write_text('{"checked_at":100,"ok":false,"ok":true,"signals":[{"name":"disk","ok":true,"detail":"1 bytes"}]}')
    assert LongTermHealthEvidenceStore(path).load() is None


def test_empty_signal_set_is_not_healthy():
    assert not LongTermHealth(100, ()).ok


def test_overlapping_ticks_do_not_run_a_second_observation():
    entered, release = threading.Event(), threading.Event()
    calls = []
    def check():
        calls.append(1)
        entered.set()
        if not release.wait(3): raise RuntimeError('test release deadline')
        return healthy()
    loop = LongTermHealthLoop(check, clock=lambda: 100)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(loop.tick)
        assert entered.wait(2)
        second = pool.submit(loop.tick)
        try:
            assert second.result(timeout=.5) is None
        finally:
            release.set()
        assert first.result(timeout=2).ok
    assert len(calls) == 1


def test_stopped_observer_does_not_start_one_more_check():
    calls = []
    loop = LongTermHealthLoop(lambda: calls.append(1) or healthy())
    loop.stop()
    loop.run()
    assert calls == []


@pytest.mark.parametrize('failure', ['check', 'save'])
def test_actual_background_observer_recovers_without_restart(tmp_path, failure):
    attempts, persisted = [], []
    recovered = threading.Event()
    store = LongTermHealthEvidenceStore(tmp_path / 'health.json')
    original = store.save
    def save(result):
        if failure == 'save' and len(attempts) == 1:
            raise OSError('DO_NOT_RECORD_storage_location')
        original(result)
        persisted.append(result.ok)
    store.save = save
    def check():
        attempts.append(1)
        if len(attempts) == 1 and failure == 'check':
            raise RuntimeError('DO_NOT_RECORD_private_request')
        return healthy()
    class Observer(LongTermHealthLoop):
        def tick(self):
            result = super().tick()
            if result is not None and result.ok:
                recovered.set()
            return result
    loop = Observer(check, clock=lambda: 100, evidence_store=store)
    loop.interval = .01  # Short test schedule only; production retains its minimum interval.
    worker = loop.start()
    try:
        assert recovered.wait(5) and len(attempts) >= 2
        assert loop.ok(stale_after=60) and store.load().ok
        if failure == 'check':
            assert persisted[:2] == [False, True]
        else:
            assert persisted[0] is True
        assert 'DO_NOT_RECORD' not in store.path.read_text()
    finally:
        loop.stop()
        worker.join(timeout=2)
    assert not worker.is_alive() and not loop.ok()


def test_frozen_or_rolled_back_wall_clock_cannot_keep_old_success_fresh():
    wall, elapsed = [100], [0]
    loop = LongTermHealthLoop(lambda: healthy(wall[0]), clock=lambda: wall[0], monotonic=lambda: elapsed[0], interval=60)
    assert loop.tick().ok and loop.ok()
    elapsed[0] = 121
    wall[0] = 101  # A small wall-clock age cannot hide the actual elapsed interval.
    assert loop.trustworthy() is None and not loop.ok()
    assert loop.tick().ok and loop.ok()


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), True, '100'])
def test_invalid_current_clock_or_freshness_limit_is_not_healthy(bad):
    wall, elapsed = [100], [0]
    loop = LongTermHealthLoop(healthy, clock=lambda: wall[0], monotonic=lambda: elapsed[0])
    loop.tick()
    assert loop.trustworthy(now=bad) is None
    assert loop.trustworthy(stale_after=bad) is None
    elapsed[0] = bad
    assert loop.trustworthy() is None


def test_new_process_instance_does_not_promote_saved_history_to_live_health(tmp_path):
    store = LongTermHealthEvidenceStore(tmp_path / 'health.json')
    store.save(healthy())
    loop = LongTermHealthLoop(healthy, clock=lambda: 100, evidence_store=store)
    assert store.load().ok
    assert loop.latest() is None and not loop.ok()
    assert loop.tick().ok and loop.ok()


def test_failed_atomic_publish_preserves_previous_record_and_cleans_temp(tmp_path, monkeypatch):
    import ai_foundation.long_term_health as module
    store = LongTermHealthEvidenceStore(tmp_path / 'health.json')
    store.save(healthy())
    before = store.path.read_bytes()
    with monkeypatch.context() as scoped:
        scoped.setattr(module.os, 'replace', lambda *args: (_ for _ in ()).throw(OSError('failed write')))
        with pytest.raises(OSError):
            store.save(healthy(101))
    assert store.path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [store.path]


def test_invalid_save_cannot_overwrite_the_previous_valid_observation(tmp_path):
    store = LongTermHealthEvidenceStore(tmp_path / 'health.json')
    store.save(healthy())
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.save(healthy(float('nan')))
    assert store.path.read_bytes() == before


def test_evidence_load_is_bounded_and_rejects_duplicate_signal_identity(tmp_path):
    from ai_foundation.long_term_health import MAX_HEALTH_EVIDENCE_BYTES
    path = tmp_path / 'health.json'
    path.write_bytes(b' ' * (MAX_HEALTH_EVIDENCE_BYTES + 1))
    store = LongTermHealthEvidenceStore(path)
    assert store.load() is None
    signal = {'name': 'disk', 'ok': True, 'detail': '1 bytes'}
    path.write_text(json.dumps({'checked_at': 100, 'ok': True, 'signals': [signal, signal]}))
    assert store.load() is None


def test_repeated_start_returns_the_same_live_observer():
    entered, release = threading.Event(), threading.Event()
    def check():
        entered.set()
        if not release.wait(3): raise RuntimeError('test release deadline')
        return healthy()
    loop = LongTermHealthLoop(check)
    worker = loop.start()
    try:
        assert entered.wait(2)
        assert loop.start() is worker
    finally:
        loop.stop()
        release.set()
        worker.join(timeout=5)
    assert not worker.is_alive()


def test_stopped_or_dead_observer_cannot_advertise_cached_success():
    loop = LongTermHealthLoop(healthy, clock=lambda: 100)
    loop.tick()
    assert loop.ok()
    loop.stop()
    assert loop.latest().ok and not loop.ok()
    other = LongTermHealthLoop(healthy, clock=lambda: 100)
    other.tick()
    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join(timeout=2)
    other._thread = dead
    assert other.latest().ok and not other.ok()
