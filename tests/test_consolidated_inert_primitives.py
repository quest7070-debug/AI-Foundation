"""Source-only PR consolidation: no model, network or local state access."""
import sqlite3
import pytest

from ai_foundation.human_model_literal_search import exact_source_matches, SearchUnavailable
from ai_foundation.muse_delivery_state import initialize

def test_complete_owner_view_stays_bounded_and_marks_disputes():
    view = {
        "source":"HumanModel", "status":"AVAILABLE",
        "execution_authority":False, "truncated":False,
        "omitted_record_ids":[], "view_revision":1, "scope":"work",
        "snapshot_sha256":"a" * 64,
        "records":[{"id":"synthetic-1", "scope":"work", "content":"Alpha fact",
                    "disputed":True, "kind":"observation"}]
    }
    hit = exact_source_matches(view, "alpha")
    assert hit["retrieval_engine"] == "literal-bounded-v1"
    assert hit["requires_evidence_review"] is True
    assert len(hit["records"]) == 1
    with pytest.raises(SearchUnavailable):
        exact_source_matches({**view, "truncated":True}, "alpha")

def test_inert_muse_state_initializes_only_explicit_memory_database():
    with sqlite3.connect(":memory:") as db:
        initialize(db)
        assert db.execute("SELECT count(*) FROM muse_delivery_events").fetchone()[0] == 0
