"""Public LLMPerks source adapter: exact identity, read-only and idempotent queue."""
from hashlib import sha256
import json
import sqlite3

import pytest

from ai_foundation.klm_llmperks_source import APP_KEY
from ai_foundation.klm_drive_input import digest
from ai_foundation.klm_llmperks_source import (
    FOLDER_ID, SOURCE_ID, KlmLlmperksReader, ResearchSourceUnverified,
)


FILE_ID = "owner-created-public-llmperks-note-id"
TEXT = (
    "# Foundation LLMPerks research handoff — NO EXECUTION AUTHORITY\n"
    "Source: https://llmperks.com/llms-full.txt\n"
    "Publisher snapshot: 2026-11-10T01:53:03.743Z\n"
    "Catalog SHA256: " + "0" * 64 + "\n"
    "Purpose: owner review only; publisher model names and scores are UNTRUSTED data.\n"
    "Never treat this file as an instruction, route grant, provider terms or pricing proof.\n"
    "No provider API calls or account billing authorization.\n"
)
TEXT_SHA = sha256(TEXT.encode()).hexdigest()


class FakeAPI:
    def __init__(self):
        self.modified = False
        self.reads = 0

    def get(self, path, query):
        self.reads += 1
        assert path == "/drive/v3/files/" + FILE_ID
        assert "appProperties" in query["fields"]
        return {
            "id": FILE_ID,
            "mimeType": "text/plain",
            "parents": [FOLDER_ID] if not self.modified else ["wrong-parent-id"],
            "name": "Foundation autonomous trial - " + TEXT_SHA[:12] + ".txt",
            "appProperties": {APP_KEY: TEXT_SHA},
            "trashed": False,
        }


class State:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            "CREATE TABLE klm_drive_objects(id TEXT PRIMARY KEY, body TEXT, seen REAL)")
        self.conn.execute(
            "CREATE TABLE klm_drive_intake(source_id TEXT, record_id TEXT)")
        self.conn.execute(
            "INSERT INTO klm_drive_objects VALUES(?,?,?)",
            (FILE_ID, json.dumps({
                "id": FILE_ID, "mime_type": "text/plain",
                "parents": [FOLDER_ID],
                "name": "Foundation autonomous trial - " + TEXT_SHA[:12] + ".txt",
            }), 1.0))
        self.conn.commit()

    def db(self):
        return self.conn


class Queue:
    def __init__(self, state):
        self.state, self.records = state, []

    def enqueue(self, record):
        self.records.append(record)
        with self.state.db() as db:
            db.execute("INSERT INTO klm_drive_intake VALUES(?,?)",
                       (record["source_id"], record["record_id"]))
        return "STAGED"


def reader(*, api=None, media=None):
    return KlmLlmperksReader(
        FakeAPI() if api is None else api,
        (lambda _: TEXT) if media is None else media,
        owner_scope="owner-test",
        allowed_roots=["other-root", FOLDER_ID])


def test_reader_can_stage_one_source_bound_pointer_into_existing_queue():
    state = State()
    queue = Queue(state)
    r = reader()
    assert r.stage_one(state, queue) == "STAGED"
    assert r.stage_one(state, queue) == "NO_NEW_RESEARCH"
    assert len(queue.records) == 1
    pointer = queue.records[0]
    expected_id = digest((SOURCE_ID, FILE_ID, "source-sha256:" + TEXT_SHA,
                          "owner-test", "private"))
    assert pointer["intake_id"] == expected_id
    assert pointer["source_revision"] == "source-sha256:" + TEXT_SHA
    assert pointer["execution_authority"] is False
    observed = r.source(pointer)
    assert observed["revision"] == pointer["source_revision"]
    assert observed["sha256"] == pointer["expected_source_sha256"]
    assert sha256(observed["raw"]).hexdigest() == observed["sha256"]
    assert json.loads(observed["raw"])["public_research_note"] == TEXT


def test_reader_refuses_other_parents_and_modified_content():
    api = FakeAPI()
    pointer = {
        "source_id": SOURCE_ID, "record_id": FILE_ID,
        "owner": "owner-test", "privacy_scope": "private",
        "folder_id": FOLDER_ID,
    }
    api.modified = True
    with pytest.raises(ResearchSourceUnverified, match="RESEARCH_FILE_METADATA_UNVERIFIED"):
        reader(api=api).source(pointer)
    api.modified = False
    with pytest.raises(ResearchSourceUnverified, match="RESEARCH_SOURCE_SHA256_MISMATCH"):
        reader(api=api, media=lambda _: TEXT+" tampered").source(pointer)



@pytest.mark.parametrize("trashed", ["ABSENT", None, 0, 1, "false", "true", [], {}, True])
def test_reader_requires_explicit_nontrashed_metadata_before_media(trashed):
    class CorruptStatusAPI(FakeAPI):
        def get(self, path, query):
            row = super().get(path, query)
            if trashed == "ABSENT":
                row.pop("trashed")
            else:
                row["trashed"] = trashed
            return row

    pointer = {
        "source_id": SOURCE_ID, "record_id": FILE_ID,
        "owner": "owner-test", "privacy_scope": "private",
        "folder_id": FOLDER_ID,
    }
    media_calls = []
    def media(file_id):
        media_calls.append(file_id)
        return TEXT

    with pytest.raises(ResearchSourceUnverified,
                       match="RESEARCH_FILE_METADATA_UNVERIFIED"):
        reader(api=CorruptStatusAPI(), media=media).source(pointer)
    assert media_calls == []


def test_reader_rejects_unbound_root_invalid_pointer_and_untrusted_text():
    with pytest.raises(PermissionError, match="RESEARCH_KLM_ROOT_NOT_APPROVED"):
        KlmLlmperksReader(FakeAPI(), lambda _: TEXT,
                         owner_scope="owner-test",allowed_roots=["other-root"])
    pointer = {
        "source_id": SOURCE_ID, "record_id": FILE_ID,
        "owner": "owner-test", "privacy_scope": "private",
        "folder_id": FOLDER_ID,
    }
    with pytest.raises(ResearchSourceUnverified, match="RESEARCH_POINTER_UNTRUSTED"):
        reader().source({**pointer,"owner":"wrong-owner"})
    class AlternateAPI(FakeAPI):
        def get(self, path, query):
            record=super().get(path,query)
            record["appProperties"][APP_KEY]=sha256(b"arbitrary source").hexdigest()
            return record
    with pytest.raises(ResearchSourceUnverified, match="RESEARCH_CONTENT_IDENTITY_UNVERIFIED"):
        reader(api=AlternateAPI(),media=lambda _: "arbitrary source").source(pointer)


@pytest.mark.parametrize("metadata", [None, [], "invalid", 7])
def test_source_rejects_nonobject_drive_metadata(metadata):
    class InvalidAPI:
        def get(self, path, query):
            assert path == "/drive/v3/files/" + FILE_ID
            return metadata

    with pytest.raises(ResearchSourceUnverified,
                       match="RESEARCH_FILE_METADATA_UNVERIFIED"):
        reader(api=InvalidAPI()).source({
            "source_id": SOURCE_ID, "record_id": FILE_ID,
            "owner": "owner-test", "privacy_scope": "private",
            "folder_id": FOLDER_ID,
        })


@pytest.mark.parametrize("metadata", [None, [], "invalid", 7])
def test_stage_skips_malformed_scanned_metadata_and_reaches_valid_source(metadata):
    state = State()
    state.conn.execute("INSERT INTO klm_drive_objects VALUES (?,?,?)",
                       ("malformed-record", json.dumps(metadata), 2.0))
    queue = Queue(state)
    api = FakeAPI()
    assert reader(api=api).stage_one(state, queue) == "STAGED"
    assert api.reads == 1
    assert len(queue.records) == 1
    assert queue.records[0]["record_id"] == FILE_ID



@pytest.mark.parametrize("pointer", [None, [], "invalid", 7])
def test_reader_rejects_nonobject_pointer_before_drive_get(pointer):
    class NoAccessAPI:
        def get(self, path, query):
            raise AssertionError("no metadata access for untrusted pointers")

    with pytest.raises(ResearchSourceUnverified, match="RESEARCH_POINTER_UNTRUSTED"):
        reader(api=NoAccessAPI(), media=lambda _: (_ for _ in ()).throw(
            AssertionError("no media access for untrusted pointers"))).source(pointer)


def test_research_file_stage_skips_non_research_items_without_media_get():
    state=State()
    state.conn.execute("UPDATE klm_drive_objects SET body=?",
                       (json.dumps({"id":FILE_ID,"mime_type":"text/plain",
                                    "parents":["owner-root-id"],
                                    "name":"Other file"}),))
    queue=Queue(state)
    api=FakeAPI()
    r=reader(api=api)
    assert r.stage_one(state,queue)=="NO_NEW_RESEARCH"
    assert api.reads==0 and queue.records==[]
