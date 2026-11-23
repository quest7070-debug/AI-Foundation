"""Existing owner-only service -> native preview -> exact Guard -> local decision."""
import json
from pathlib import Path
import sqlite3

import pytest

from test_klm_review_source import native
from scripts import m1_klm_owner_review as owner
from ai_foundation.klm_review_source import NativeKlmReviewReader, NativeReviewSourceError
from ai_foundation.operator_actions import OperatorActions


@pytest.fixture
def service(native):
    journal, guard, reader, atoms, values, gets, args = native
    journal.path.chmod(0o600)
    backend = owner.OwnerKlmReview(
        journal.path.parent, work_path=journal.path, authenticated_owner="fixture-owner",
        guard=guard, canon=args["canon"],
        reader_factory=lambda scope: NativeKlmReviewReader(
            journal, authenticated_owner="fixture-owner", scope=scope, inbox=reader.inbox))
    return backend, journal, guard, atoms, values, gets, args["review_key"]


def test_list_and_preview_are_readonly_but_preview_reads_actual_native_spans(service):
    backend, journal, guard, atoms, values, gets, key = service
    before = journal.path.read_bytes()
    rows = backend.list_reviews()
    assert [row["review_key"] for row in rows["reviews"]] == [key]
    assert not gets
    preview = backend.preview(key)
    assert {preview["before"]["span_text"], preview["after"]["span_text"]} == {
        "first source", "second source"}
    assert preview["semantic_accuracy_verified"] is False and preview["model_calls"] == 0
    assert len(preview["preview_token"]) == 64
    assert len(gets) > 0 and journal.path.read_bytes() == before
    with guard.store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM approval_requests").fetchone()[0] == 0


def test_exact_pending_uses_existing_operator_approval_then_native_resolve(service):
    backend, journal, guard, atoms, values, gets, key = service
    preview = backend.preview(key)
    fields = dict(preview_token=preview["preview_token"], decision="ACCEPT", relation_kind="supports")
    result = backend.request(key, **fields)
    assert result["status"] == "WAITING_HUMAN" and result["approval_ref"]
    assert result["preview_token"] == preview["preview_token"]
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT COUNT(*) FROM klm_relation_dispositions").fetchone()[0] == 0
    with pytest.raises(PermissionError, match="EXACT_GUARD"):
        backend.resolve(key, **fields)
    assert OperatorActions(guard).approve_pending(result["run_id"], result["approval_ref"]).ok
    source_reads = len(gets)
    assert backend.resolve(key, **fields)["status"] == "RECORDED"
    assert len(gets) > source_reads
    assert backend.resolve(key, **fields)["status"] == "ALREADY_RECORDED"
    assert backend.list_reviews()["reviews"] == []
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT COUNT(*) FROM klm_relation_dispositions").fetchone()[0] == 1


def test_source_drift_stale_preview_and_cancelled_guard_never_resolve(service):
    backend, journal, guard, atoms, values, gets, key = service
    preview = backend.preview(key)
    fields = dict(preview_token=preview["preview_token"], decision="REJECT")
    with pytest.raises(owner.KlmOwnerReviewError, match="PREVIEW_CHANGED"):
        backend.request(key, **dict(fields, preview_token="0" * 64))
    result = backend.request(key, **fields)
    assert OperatorActions(guard).approve_pending(result["run_id"], result["approval_ref"]).ok
    values[1][1] = "changed original source"
    with pytest.raises(NativeReviewSourceError, match="HISTORY_OR_REVISION"):
        backend.resolve(key, **fields)
    values[1][1] = "first source"
    guard.cancel(result["run_id"])
    with pytest.raises(PermissionError, match="EXACT_GUARD"):
        backend.resolve(key, **fields)
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT COUNT(*) FROM klm_relation_dispositions").fetchone()[0] == 0


def test_restart_requires_new_preview_but_retains_exact_pending_run(service):
    backend, journal, guard, atoms, values, gets, key = service
    preview = backend.preview(key)
    fields = dict(preview_token=preview["preview_token"], decision="REJECT")
    first = backend.request(key, **fields)
    restarted = owner.OwnerKlmReview(
        journal.path.parent, work_path=journal.path, authenticated_owner=backend.owner,
        guard=guard, canon=backend.canon, reader_factory=backend.reader_factory)
    with pytest.raises(owner.KlmOwnerReviewError, match="PREVIEW_CHANGED"):
        restarted.request(key, **fields)
    fresh = restarted.preview(key)
    second = restarted.request(key, preview_token=fresh["preview_token"], decision="REJECT")
    assert (first["run_id"], first["approval_ref"]) == (second["run_id"], second["approval_ref"])


def test_bounded_list_cursor_and_missing_provenance_stay_explicit(service):
    backend, journal, guard, atoms, values, gets, key = service
    for limit in (0, 51, True):
        with pytest.raises(owner.KlmOwnerReviewError):
            backend.list_reviews(limit=limit)
    with pytest.raises(owner.KlmOwnerReviewError):
        backend.list_reviews(after="not-a-key")
    assert backend.list_reviews(after=key)["reviews"] == []
    with sqlite3.connect(journal.path) as db:
        db.execute("DELETE FROM klm_drive_intake")
    assert backend.list_reviews()["reviews"][0]["review_key"] == key
    with pytest.raises(NativeReviewSourceError, match="PROVENANCE_UNAVAILABLE"):
        backend.preview(key)
    assert not gets


def test_storage_refuses_new_pending_but_existing_exact_decision_replay_is_readonly(service):
    backend, journal, guard, atoms, values, gets, key = service
    preview = backend.preview(key)
    fields = dict(preview_token=preview["preview_token"], decision="REJECT")
    class Denied:
        def require(self, operation):
            raise RuntimeError("STORAGE_DENIED")
    backend.storage = Denied()
    with pytest.raises(RuntimeError, match="STORAGE_DENIED"):
        backend.request(key, **fields)
    backend.storage = None
    pending = backend.request(key, **fields)
    assert OperatorActions(guard).approve_pending(pending["run_id"], pending["approval_ref"]).ok
    backend.resolve(key, **fields)
    backend.storage = Denied()
    before = journal.path.read_bytes()
    assert backend.resolve(key, **fields)["status"] == "ALREADY_RECORDED"
    assert journal.path.read_bytes() == before


def test_installed_binding_is_lazy_same_root_and_rechecks_config(service, monkeypatch):
    backend, journal, guard, atoms, values, gets, key = service
    from scripts import m1_klm_status_probe as probe
    import ai_foundation.macos_keychain as keychain
    root = journal.path.parent
    root_config = root / "config.json"
    root_config.write_text(json.dumps({"work_db": str(journal.path), "data_dir": str(root)}))
    root_config.chmod(0o600)
    host_config = root / "klm-host.json"
    host_config.write_text(json.dumps({"foundation_root": str(root), "owner_scope": backend.owner,
                                      "roots": ["fixed-existing-root"]}))
    host_config.chmod(0o600)
    monkeypatch.setattr(owner, "_require_owner_host", lambda: None)
    monkeypatch.setattr(probe, "_fixed_service_paths", lambda home: (root / "report.json", host_config))
    def forbidden_keychain():
        raise AssertionError("constructor/list must not discover or read credentials")
    monkeypatch.setattr(keychain, "MacOSKeychain", forbidden_keychain)
    installed = owner.OwnerKlmReview.from_installed(root, guard=guard, canon=backend.canon)
    assert installed.list_reviews()["reviews"][0]["review_key"] == key
    host_config.write_text(json.dumps({"foundation_root": str(root), "owner_scope": "changed-owner",
                                      "roots": ["fixed-existing-root"]}))
    with pytest.raises(owner.KlmOwnerReviewError, match="BINDING_CHANGED"):
        installed.list_reviews()
    assert not gets


def test_host_binding_rejects_reader_from_another_owner_or_database(service):
    backend, journal, guard, atoms, values, gets, key = service
    real = backend.reader_factory
    def wrong_owner(scope):
        reader = real(scope)
        reader.owner = "different-owner"
        return reader
    backend.reader_factory = wrong_owner
    with pytest.raises(owner.KlmOwnerReviewError, match="SAME_OWNER_NATIVE_SOURCE"):
        backend.preview(key)
    assert not gets


def test_legacy_disposition_schema_is_created_only_after_exact_approval(service):
    backend, journal, guard, atoms, values, gets, key = service
    with sqlite3.connect(journal.path) as db:
        db.execute("DROP TABLE klm_relation_dispositions")
    # Construct/read the already installed old KLM DB without migration.
    backend = owner.OwnerKlmReview(
        journal.path.parent, work_path=journal.path, authenticated_owner=backend.owner,
        guard=guard, canon=backend.canon, reader_factory=backend.reader_factory)
    before = journal.path.read_bytes()
    backend.list_reviews()
    preview = backend.preview(key)
    assert journal.path.read_bytes() == before
    fields = dict(preview_token=preview["preview_token"], decision="REJECT")
    pending = backend.request(key, **fields)
    def has_table():
        with sqlite3.connect(journal.path) as db:
            return db.execute("SELECT 1 FROM sqlite_master "
                              "WHERE name='klm_relation_dispositions'").fetchone()
    assert not has_table()
    with pytest.raises(PermissionError, match="EXACT_GUARD"):
        backend.resolve(key, **fields)
    assert not has_table()
    assert OperatorActions(guard).approve_pending(pending["run_id"], pending["approval_ref"]).ok
    with pytest.raises(owner.KlmOwnerReviewError, match="STORAGE_ADMISSION_UNBOUND"):
        backend.resolve(key, **fields)
    assert not has_table()
    class Storage:
        calls = 0
        def require(self, operation):
            self.calls += 1
    storage = Storage()
    backend.storage = storage
    assert backend.resolve(key, **fields)["status"] == "RECORDED"
    assert storage.calls == 1 and has_table()
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT decision FROM klm_relation_dispositions").fetchall() == [("REJECT",)]
        assert db.execute("SELECT status FROM klm_relation_reviews").fetchall() == [("UNRESOLVED",)]


def test_saved_feature_drift_invalidates_preview_before_any_native_read(service):
    backend, journal, guard, atoms, values, gets, key = service
    preview = backend.preview(key)
    reads = len(gets)
    with sqlite3.connect(journal.path) as db:
        db.execute("UPDATE klm_atom_features SET subject=?", ("0" * 64,))
    with pytest.raises(owner.KlmOwnerReviewError, match="PREVIEW_CHANGED"):
        backend.request(key, preview_token=preview["preview_token"], decision="REJECT")
    assert len(gets) == reads
