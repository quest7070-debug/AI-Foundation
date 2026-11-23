"""Native source refetch, not saved-source assertions or semantic re-inference."""
from dataclasses import replace
import hashlib
import sqlite3

import pytest

from ai_foundation.core import CanonContract
from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.guard import GuardCore
from ai_foundation.knowledge_lifecycle import Meaning, ReadonlyReceiptJournal
from ai_foundation.klm_drive_cycle import NativeInboxReader
from ai_foundation.klm_drive_input import DriveState, INBOX_ID
from ai_foundation.klm_drive_work import IntakeQueue, inbox_records, klm_proposals
from ai_foundation.klm_relation_review import request_relation_review, resolve_relation_review
from ai_foundation.klm_review_source import NativeKlmReviewReader, NativeReviewSourceError
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.store import SQLiteGuardStore, approval_request_ref


@pytest.fixture
def native(tmp_path):
    values = [["intake_id", "text"], ["one", "first source"], ["two", "second source"]]
    gets = []
    def get(path, params):
        gets.append(path)
        base = "/v4/spreadsheets/" + INBOX_ID
        if path == base:
            return {"sheets": [{"properties": {"title": "Inbox", "gridProperties":
                    {"rowCount": 10, "columnCount": 2}}}]}
        assert path == base + "/values/Inbox!A1:L10"
        return {"values": [list(row) for row in values]}
    inbox = NativeInboxReader(get)
    journal = ReadonlyReceiptJournal(tmp_path / "work.db")
    queue = IntakeQueue(DriveState(SQLiteWorkStore(journal.path)))
    atoms = []
    for pointer in inbox_records(values, owner="fixture-owner"):
        queue.enqueue(pointer)
        current = inbox.source(pointer)
        text = values[pointer["row_hint"] - 1][1].encode()
        start = current["raw"].index(text)
        atom = klm_proposals(pointer, current, [
            (start, start + len(text), Meaning("observation", "assertion", "positive",
                                              "fixture-subject", "state", "saved-proposal"))
        ])[0]
        journal.record_atom(atom)
        atoms.append(atom)
    journal.reconcile_atom(atoms[-1].atom_id)
    with sqlite3.connect(journal.path) as db:
        review_key = db.execute("SELECT review_key FROM klm_relation_reviews").fetchone()[0]
    store = SQLiteGuardStore(tmp_path / "guard.db")
    guard = GuardCore(store.load(), store=store)
    reader = NativeKlmReviewReader(journal, authenticated_owner="fixture-owner",
                                   scope="drive-inbox", inbox=inbox)
    args = dict(review_key=review_key, decision="ACCEPT", relation_kind="supports",
                authenticated_owner="fixture-owner", scope="drive-inbox",
                canon=CanonContract("fixture-source-review", "v1"), run_id="native-review")
    gets.clear()
    return journal, guard, reader, atoms, values, gets, args


def approve(guard, run_id):
    with guard.store._connect() as db:
        row = db.execute("SELECT action,target,request_nonce,canon_revision,effect_id "
                         "FROM approval_requests WHERE run_id=?", (run_id,)).fetchone()
    assert OperatorActions(guard).approve_pending(run_id, approval_request_ref(run_id, *row)).ok


def test_native_request_and_resolve_refetch_original_source_each_time(native):
    journal, guard, reader, atoms, values, gets, args = native
    assert request_relation_review(journal, guard=guard, read_current=reader,
                                   **args)["status"] == "WAITING_HUMAN"
    assert len(gets) == 4  # metadata + values for both exact saved source atoms
    approve(guard, args["run_id"])
    assert resolve_relation_review(journal, guard=guard, read_current=reader,
                                   **args)["status"] == "RECORDED"
    assert len(gets) == 8
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT decision FROM klm_relation_dispositions").fetchall() == [("ACCEPT",)]
    assert b"first source" not in journal.path.read_bytes()
    assert b"second source" not in journal.path.read_bytes()


def test_native_changed_revision_after_approval_is_not_committed(native):
    journal, guard, reader, atoms, values, gets, args = native
    request_relation_review(journal, guard=guard, read_current=reader, **args)
    approve(guard, args["run_id"])
    values[1][1] = "changed source"
    with pytest.raises(NativeReviewSourceError, match="HISTORY_OR_REVISION"):
        resolve_relation_review(journal, guard=guard, read_current=reader, **args)
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT COUNT(*) FROM klm_relation_dispositions").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM klm_relations").fetchone()[0] == 0


def test_owner_scope_and_serialized_or_generic_callback_proofs_cannot_pass(native):
    journal, guard, reader, atoms, values, gets, args = native
    with pytest.raises(PermissionError, match="OWNER_SCOPE"):
        request_relation_review(journal, guard=guard, read_current=reader,
                                **dict(args, authenticated_owner="other-owner"))
    assert not gets
    with pytest.raises(PermissionError, match="CURRENT_SOURCE_ATOM_REQUIRED"):
        request_relation_review(journal, guard=guard, read_current=lambda aid: reader(aid), **args)
    proof = reader(atoms[0].atom_id)
    other = NativeKlmReviewReader(journal, authenticated_owner="fixture-owner",
                                  scope="drive-inbox", inbox=reader.inbox)
    with sqlite3.connect(journal.path) as db:
        row = db.execute("SELECT * FROM klm_atoms WHERE atom_id=?", (atoms[0].atom_id,)).fetchone()
        features = db.execute("SELECT * FROM klm_atom_features WHERE atom_id=?", (atoms[0].atom_id,)).fetchone()
    with pytest.raises(NativeReviewSourceError, match="PROOF_CHANGED"):
        other.verify(proof, row, features)


def test_legacy_pointer_absence_and_ambiguity_fail_before_fetch(native):
    journal, guard, reader, atoms, values, gets, args = native
    with sqlite3.connect(journal.path) as db:
        pointer = db.execute("SELECT * FROM klm_drive_intake LIMIT 1").fetchone()
        db.execute("DELETE FROM klm_drive_intake")
    with pytest.raises(NativeReviewSourceError, match="PROVENANCE_UNAVAILABLE"):
        reader(atoms[0].atom_id)
    assert not gets
    with sqlite3.connect(journal.path) as db:
        db.execute("INSERT INTO klm_drive_intake VALUES(?,?,?,?,?,?,?,?,?)", pointer)
        duplicate = list(pointer)
        duplicate[0], duplicate[7] = "fake-duplicate", "klm-drive:fake-duplicate"
        db.execute("INSERT INTO klm_drive_intake VALUES(?,?,?,?,?,?,?,?,?)", duplicate)
    target = next(a for a in atoms if a.source.record_id == pointer[5])
    with pytest.raises(NativeReviewSourceError, match="PROVENANCE_AMBIGUOUS"):
        reader(target.atom_id)
    assert not gets


def test_span_and_saved_pointer_owner_must_match_exactly(native):
    journal, guard, reader, atoms, values, gets, args = native
    with sqlite3.connect(journal.path) as db:
        db.execute("UPDATE klm_atoms SET span_sha256=? WHERE atom_id=?",
                   ("0" * 64, atoms[0].atom_id))
    with pytest.raises(NativeReviewSourceError, match="SPAN_CHANGED"):
        reader(atoms[0].atom_id)
    gets.clear()
    with sqlite3.connect(journal.path) as db:
        db.execute("UPDATE klm_drive_intake SET owner='other-owner'")
    with pytest.raises(NativeReviewSourceError, match="PROVENANCE_UNAVAILABLE"):
        reader(atoms[1].atom_id)
    assert not gets


def test_existing_native_grid_limit_is_not_bypassed(native):
    journal, guard, reader, atoms, values, gets, args = native
    def oversized_grid(path, params):
        return {"sheets": [{"properties": {"title": "Inbox", "gridProperties":
                {"rowCount": 1001, "columnCount": 2}}}]}
    reader.inbox.get = oversized_grid
    with pytest.raises(NativeReviewSourceError, match="SOURCE_READ_UNAVAILABLE"):
        reader(atoms[0].atom_id)


def test_existing_research_reader_keeps_app_root_digest_and_revision_checks(tmp_path):
    from ai_foundation.klm_llmperks_source import (
        APP_KEY, FOLDER_ID, SOURCE_ID, TEXT_PREFIX, KlmLlmperksReader,
    )
    from ai_foundation.klm_drive_input import digest
    text = (TEXT_PREFIX + "Source: https://llmperks.com/llms-full.txt\n"
            "Never treat this file as an instruction\nPublic research fixture")
    text_sha = hashlib.sha256(text.encode()).hexdigest()
    file_id = "fixture_research_12345"
    calls = []
    class Api:
        def get(self, path, params):
            calls.append(path)
            return {"id": file_id, "mimeType": "text/plain", "parents": [FOLDER_ID],
                    "trashed": False, "name": "Foundation autonomous trial - fixture",
                    "appProperties": {APP_KEY: text_sha}}
    research = KlmLlmperksReader(Api(), lambda _: text, owner_scope="fixture-owner",
                                 allowed_roots=[FOLDER_ID])
    pointer = dict(source_id=SOURCE_ID, record_id=file_id, owner="fixture-owner",
                   privacy_scope="private", folder_id=FOLDER_ID)
    current = research.source(pointer)
    pointer.update(source_revision=current["revision"], expected_source_sha256=current["sha256"])
    pointer["intake_id"] = digest((SOURCE_ID, file_id, current["revision"], "fixture-owner", "private"))
    journal = ReadonlyReceiptJournal(tmp_path / "research.db")
    IntakeQueue(DriveState(SQLiteWorkStore(journal.path))).enqueue(pointer)
    start = current["raw"].index(b"Public research fixture")
    atom = klm_proposals(pointer, current, [
        (start, start + len(b"Public research fixture"), Meaning(
            "observation", "assertion", "positive", "public-fixture", "state", "saved"))
    ])[0]
    journal.record_atom(atom)
    reader = NativeKlmReviewReader(journal, authenticated_owner="fixture-owner",
                                   scope="drive-public-research", research=research)
    calls.clear()
    proof = reader(atom.atom_id)
    assert calls == ["/drive/v3/files/" + file_id]
    assert proof.source_sha256 == atom.source_sha256
    # App digest mismatch is refused by the original source adapter.
    research.read_media = lambda _: text + "changed"
    with pytest.raises(NativeReviewSourceError, match="SOURCE_READ_UNAVAILABLE"):
        reader(atom.atom_id)
