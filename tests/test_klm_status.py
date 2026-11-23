import sqlite3
from hashlib import sha256
from types import SimpleNamespace
from ai_foundation.klm_status import CachedKlmLifecycleStatus, lifecycle_status
from ai_foundation.human_renderer import _overview


def _database(path):
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE klm_atoms(atom_id TEXT, private_source TEXT);
            CREATE TABLE klm_atom_features(atom_id TEXT);
            CREATE TABLE klm_relation_reviews(status TEXT);
            CREATE TABLE klm_relations(private_relation TEXT);
            CREATE TABLE klm_drive_intake(job_id TEXT);
            CREATE TABLE work_steps(job_id TEXT,position INTEGER,status TEXT);
            INSERT INTO klm_atoms VALUES('one','PRIVATE_CANARY'),('two','PRIVATE_CANARY');
            INSERT INTO klm_atom_features VALUES('one');
            INSERT INTO klm_relation_reviews VALUES('UNRESOLVED'),('UNRESOLVED');
            INSERT INTO klm_drive_intake VALUES('job');
            INSERT INTO work_steps VALUES('job',0,'FAILED');
        """)


def test_missing_database_is_unverified_and_never_created(tmp_path):
    path = tmp_path / 'absent.sqlite'
    assert lifecycle_status(path) == {'state': 'UNVERIFIED'}
    assert not path.exists()


def test_counts_are_independent_readonly_and_sync_does_not_hide_pending_work(tmp_path):
    path = tmp_path / 'work.sqlite'
    _database(path)
    before = sha256(path.read_bytes()).hexdigest()
    row = lifecycle_status(path, wall_clock=lambda: 1700000000)
    assert row == {'state': 'OBSERVED', 'atoms': 2, 'missing_features': 1,
                   'unresolved_reviews': 2, 'relations': 0, 'failed_intake': 1,
                   'observed_at': 1700000000}
    assert sha256(path.read_bytes()).hexdigest() == before
    dev = {'klm_lifecycle_state': row['state'], 'klm_status': 'CURRENT'}
    dev.update({'klm_'+k: v for k,v in row.items() if k != 'state'})
    dev['klm_lifecycle_observed_at'] = row['observed_at']
    dev['klm_lifecycle_snapshot_age_seconds'] = 12
    view = SimpleNamespace(development=dev, telemetry=None, activity=(),
                           providers=(), runtime_health='UNVERIFIED')
    page = _overview(view)
    assert '\u540c\u671f\u5b8c\u4e86' in page and '\u78ba\u8a8d\u5f85\u3061\u3042\u308a' in page
    assert '1700000000' not in page
    assert 'PRIVATE_CANARY' not in str(row) + page


def test_local_review_triage_counts_only_allowlisted_reasons_without_leaking_text(tmp_path):
    path = tmp_path / 'work.sqlite'
    _database(path)
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE klm_relation_reviews ADD COLUMN reason TEXT")
        db.execute("UPDATE klm_relation_reviews SET reason=? WHERE rowid=1",
                   ("POTENTIAL_CONTRADICTION",))
        db.execute("UPDATE klm_relation_reviews SET reason=? WHERE rowid=2",
                   ("UNKNOWN_POLARITY_REVIEW",))
    before = sha256(path.read_bytes()).hexdigest()
    row = lifecycle_status(path, wall_clock=lambda: 1700000000)
    assert row["unresolved_reviews"] == 2
    assert row["review_triage"] == {
        "conflict": 1, "revision": 0, "qualifier": 0, "dependency": 0,
        "difference": 0, "duplicate": 0, "other": 1,
    }
    assert "UNKNOWN_POLARITY_REVIEW" not in str(row)
    assert sha256(path.read_bytes()).hexdigest() == before
    dev = {"klm_review_triage": row["review_triage"],
           "klm_lifecycle_state": "OBSERVED", "klm_unresolved_reviews": 2}
    view = SimpleNamespace(development=dev, telemetry=None, activity=(),
                           providers=(), runtime_health="UNVERIFIED")
    page = _overview(view)
    assert "\u78ba\u8a8d\u5f85\u3061\u3042\u308a" in page
    assert "UNKNOWN_POLARITY_REVIEW" not in page


def test_stalled_klm_snapshot_does_not_block_other_operator_requests(
        tmp_path, monkeypatch):
    from threading import Event, Thread
    from time import monotonic
    import ai_foundation.klm_status as status

    entered, released = Event(), Event()
    observed, calls = [], []
    def blocked(_path):
        calls.append("read")
        entered.set()
        assert released.wait(3)
        return {"state": "OBSERVED", "atoms": 2, "observed_at": 1700000000}

    monkeypatch.setattr(status, "lifecycle_status", blocked)
    cache = CachedKlmLifecycleStatus(tmp_path / "not-read.sqlite")
    worker = Thread(target=lambda: observed.append(cache()), daemon=True)
    worker.start()
    try:
        assert entered.wait(2)
        start = monotonic()
        assert cache() == {"state": "UNVERIFIED"}
        assert monotonic() - start < 1
        assert calls == ["read"]
    finally:
        released.set()
        worker.join(timeout=3)
    assert not worker.is_alive()
    assert observed[0]["atoms"] == 2
    assert cache()["atoms"] == 2
    assert calls == ["read"]


def test_cached_review_triage_return_is_not_mutable_shared_state(tmp_path):
    path = tmp_path / 'work.sqlite'
    _database(path)
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE klm_relation_reviews ADD COLUMN reason TEXT")
        db.execute("UPDATE klm_relation_reviews SET reason='DEPENDENCY_REVIEW'")
    read = CachedKlmLifecycleStatus(path)
    first = read()
    first["review_triage"]["dependency"] = 999
    assert read()["review_triage"]["dependency"] == 2


def test_overview_marks_unobserved_index_time_and_age_as_unknown():
    for timestamp in (None, True, '1700000000', -1):
        view = SimpleNamespace(
            development={'klm_lifecycle_observed_at': timestamp},
            telemetry=None, activity=(), providers=(), runtime_health='UNVERIFIED')
        page = _overview(view)
        assert '\u672a\u78ba\u8a8d' in page
        assert 'SNAPSHOT AGE' not in page


def test_missing_tables_and_symlinks_never_become_zero_pending(tmp_path):
    path = tmp_path / 'partial.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE klm_atoms(atom_id TEXT)')
    assert lifecycle_status(path) == {'state': 'UNVERIFIED'}
    link = tmp_path / 'alias.sqlite'
    link.symlink_to(path)
    assert lifecycle_status(link) == {'state': 'UNVERIFIED'}


def test_ui_refresh_reuses_counts_until_thirty_second_expiry(tmp_path):
    path = tmp_path / 'work.sqlite'
    _database(path)
    now = [100.0]
    read = CachedKlmLifecycleStatus(path, clock=lambda: now[0])
    first = read()
    assert first['snapshot_age_seconds'] == 0
    observed_at = first['observed_at']
    first['atoms'] = 999
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO klm_atoms VALUES('three','PRIVATE_CANARY')")
    now[0] = 129.9
    assert read()['atoms'] == 2
    assert read()['snapshot_age_seconds'] == 29
    assert read()['observed_at'] == observed_at
    now[0] = 130.0
    assert read()['atoms'] == 3
    assert read()['snapshot_age_seconds'] == 0


def test_expired_read_failure_drops_old_counts_and_observation_time(tmp_path):
    path = tmp_path / 'work.sqlite'
    _database(path)
    now = [100.0]
    read = CachedKlmLifecycleStatus(path, clock=lambda: now[0])
    assert read()['state'] == 'OBSERVED'
    path.unlink()
    now[0] = 130.0
    assert read() == {'state': 'UNVERIFIED'}
    assert not path.exists()
