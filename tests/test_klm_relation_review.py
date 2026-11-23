"""Exact owner-local KLM decisions; real Guard store, synthetic source adapters."""
import hashlib
import sqlite3
from dataclasses import replace

import pytest

from ai_foundation.core import CanonContract
from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.guard import GuardCore
from ai_foundation.knowledge_lifecycle import (
    Meaning, SourcePointer, ReadonlyReceiptJournal, RelationProposal,
    decompose_verified_span,
)
from ai_foundation.klm_relation_review import (
    relation_review_intent, request_relation_review, resolve_relation_review,
    unresolved_review_filter,
)
from ai_foundation.klm_status import lifecycle_status
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.store import SQLiteGuardStore, approval_request_ref
from scripts.m1_klm_status_probe import _lifecycle_counts


def atom(record, revision="1", privacy="private"):
    raw = b"synthetic owner-local evidence"
    return decompose_verified_span(
        SourcePointer("foundation_runtime", "fixture-root", record,
                      revision, "fixture-scope", privacy),
        raw, source_sha256=hashlib.sha256(raw).hexdigest(), start=0, end=len(raw),
        meaning=Meaning("observation", "assertion", "positive",
                        "fixture-subject", "status", "ready"))


@pytest.fixture
def context(tmp_path):
    journal = ReadonlyReceiptJournal(tmp_path / "work.db")
    a, b = atom("one"), atom("two")
    journal.record_atom(a)
    journal.record_atom(b)
    journal.reconcile_atom(b.atom_id)
    SQLiteWorkStore(journal.path)
    with sqlite3.connect(journal.path) as db:
        db.execute("CREATE TABLE klm_drive_intake(job_id TEXT)")
        key = db.execute("SELECT review_key FROM klm_relation_reviews").fetchone()[0]
    store = SQLiteGuardStore(tmp_path / "guard.db")
    guard = GuardCore(store.load(), store=store)
    sources = {a.atom_id: a, b.atom_id: b}
    args = dict(review_key=key, decision="ACCEPT", relation_kind="supports",
                authenticated_owner="fixture-owner", scope="fixture-scope",
                canon=CanonContract("fixture-owner-review", "fixture-v1"),
                run_id="fixture-review-1")
    return journal, store, guard, sources, args


def approved(context, args=None):
    journal, store, guard, sources, original = context
    args = original if args is None else args
    assert request_relation_review(journal, guard=guard,
                                   read_current=sources.__getitem__, **args)["status"] == "WAITING_HUMAN"
    with store._connect() as db:
        row = db.execute("SELECT action,target,request_nonce,canon_revision,effect_id "
                         "FROM approval_requests WHERE run_id=?", (args["run_id"],)).fetchone()
    assert OperatorActions(guard).approve_pending(
        args["run_id"], approval_request_ref(args["run_id"], *row)).ok


def counts(journal):
    with sqlite3.connect(journal.path) as db:
        return db.execute("SELECT COUNT(*) FROM klm_relation_reviews r WHERE "
                          + unresolved_review_filter(db)).fetchone()[0]


def test_real_pending_approval_acceptance_replay_and_all_count_readers(context):
    journal, store, guard, sources, args = context
    before = journal.path.read_bytes()
    with pytest.raises(PermissionError, match="EXACT_GUARD"):
        resolve_relation_review(journal, guard=guard, read_current=sources.__getitem__, **args)
    assert journal.path.read_bytes() == before and counts(journal) == 1
    intent = relation_review_intent(journal, **args)
    assert "fixture-root" not in intent.target and len(intent.effect_id) == 64
    approved(context)
    with sqlite3.connect(journal.path) as db:
        candidate = db.execute("SELECT * FROM klm_relation_reviews").fetchone()
    assert resolve_relation_review(journal, guard=guard, read_current=sources.__getitem__,
                                   **args) == {"status": "RECORDED", "decision": "ACCEPT"}
    assert resolve_relation_review(journal, guard=guard, read_current=sources.__getitem__,
                                   **args)["status"] == "ALREADY_RECORDED"
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT * FROM klm_relation_reviews").fetchone() == candidate
        assert db.execute("SELECT status FROM klm_relations").fetchall() == [("owner_verified",)]
        assert db.execute("SELECT COUNT(*) FROM klm_relation_dispositions").fetchone()[0] == 1
        assert _lifecycle_counts(db)["unresolved_reviews"] == 0
        a, b = candidate[1:3]
    # An identical proposal replays without downgrading the approved edge.
    assert journal.record_relation(RelationProposal("supports", a, b)) == "ALREADY_RECORDED"
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT status FROM klm_relations").fetchall() == [("owner_verified",)]
    result = lifecycle_status(journal.path)
    assert result["unresolved_reviews"] == 0 and sum(result["review_triage"].values()) == 0
    receipt = journal.audit_due(SQLiteWorkStore(journal.path), now=1794000000)["daily"]
    assert receipt["unresolved_relations"] == 0
    assert b"synthetic owner-local evidence" not in journal.path.read_bytes()


def test_run_only_grant_and_stale_decision_are_rejected(context):
    journal, store, guard, sources, args = context
    guard.approve(args["run_id"])
    with pytest.raises(PermissionError):
        resolve_relation_review(journal, guard=guard, read_current=sources.__getitem__, **args)
    # A fresh exact run is approved via the normal existing pending UI path.
    args = dict(args, run_id="fixture-review-2")
    approved(context, args)
    changed = dict(args, decision="REJECT", relation_kind="")
    with pytest.raises(PermissionError):
        resolve_relation_review(journal, guard=guard, read_current=sources.__getitem__, **changed)
    assert counts(journal) == 1


def test_rejection_preserves_candidates_without_creating_an_edge(context):
    journal, store, guard, sources, args = context
    args = dict(args, decision="REJECT", relation_kind="")
    approved(context, args)
    assert resolve_relation_review(journal, guard=guard, read_current=sources.__getitem__,
                                   **args)["decision"] == "REJECT"
    assert counts(journal) == 0
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT COUNT(*) FROM klm_relations").fetchone()[0] == 0
        assert db.execute("SELECT status FROM klm_relation_reviews").fetchone()[0] == "UNRESOLVED"
    changed = dict(args, run_id="fixture-review-2", decision="ACCEPT", relation_kind="supports")
    approved(context, changed)
    with pytest.raises(PermissionError, match="IMMUTABLE_REVIEW"):
        resolve_relation_review(journal, guard=guard, read_current=sources.__getitem__, **changed)
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT COUNT(*) FROM klm_relations").fetchone()[0] == 0


def test_changed_source_or_cancellation_during_read_never_commits(context):
    journal, store, guard, sources, args = context
    approved(context)
    key = next(iter(sources))
    original = sources[key]
    sources[key] = atom(original.source.record_id, revision="2")
    with pytest.raises(PermissionError, match="SOURCE_REVISION"):
        resolve_relation_review(journal, guard=guard, read_current=sources.__getitem__, **args)
    sources[key] = original
    def cancelled_reader(atom_id):
        guard.cancel(args["run_id"])
        return sources[atom_id]
    with pytest.raises(PermissionError, match="CANCELLED"):
        resolve_relation_review(journal, guard=guard, read_current=cancelled_reader, **args)
    assert counts(journal) == 1
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT COUNT(*) FROM klm_relation_dispositions").fetchone()[0] == 0


def test_scope_owner_pins_and_privacy_boundary(context):
    journal, store, guard, sources, args = context
    intent = relation_review_intent(journal, **args)
    assert relation_review_intent(journal, **dict(args, authenticated_owner="different")).target != intent.target
    with pytest.raises(PermissionError):
        relation_review_intent(journal, **dict(args, scope="other"))
    with sqlite3.connect(journal.path) as db:
        atom_id = db.execute("SELECT before_id FROM klm_relation_reviews").fetchone()[0]
        db.execute("UPDATE klm_atoms SET privacy='shareable' WHERE atom_id=?", (atom_id,))
    with pytest.raises(PermissionError, match="BOUNDARY"):
        request_relation_review(journal, guard=guard, read_current=sources.__getitem__, **args)
    assert not store.is_approved(args["run_id"])
