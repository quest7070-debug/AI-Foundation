"""Contract tests for the private Raw-linked evidence audit journal."""
import hashlib
import sqlite3
import pytest

from experiments.human_model.evidence_audit import EvidenceAudit

class Inbox:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("CREATE TABLE raw_items (id TEXT PRIMARY KEY, source_uri TEXT, content_sha256 TEXT)")
        self.db.execute("INSERT INTO raw_items VALUES ('r1','chat:example','abc')")

def args(**kw):
    d = dict(raw_id="r1", digest="abc", source_uri="chat:example",
             event_type="source_discovered", actor="assistant",
             evidence_quality="direct", dedupe_key="source:1")
    d.update(kw)
    return d

def test_idempotent_and_conflict():
    audit = EvidenceAudit(Inbox())
    assert audit.append(**args()) is True
    assert audit.append(**args()) is False
    with pytest.raises(ValueError, match="conflicting"):
        audit.append(**args(actor="user"))
    assert len(audit.list_metadata()) == 1

def test_source_integrity_and_links():
    audit = EvidenceAudit(Inbox())
    with pytest.raises(ValueError, match="mismatch"):
        audit.append(**args(digest="wrong"))
    with pytest.raises(ValueError, match="unresolved"):
        audit.append(**args(related_event_ids=("missing",)))
    assert audit.append(**args())
    eid = audit.list_metadata()[0]["event_id"]
    assert audit.append(**args(dedupe_key="correction:1", event_type="attribution_corrected",
                               related_event_ids=(eid,), actor="user"))
    assert len(audit.list_metadata()) == 2

def test_unknown_time_and_no_implicit_approval():
    audit = EvidenceAudit(Inbox())
    assert audit.append(**args(observed_at=None))
    with pytest.raises(ValueError, match="timezone"):
        audit.append(**args(dedupe_key="badtime", observed_at="2026-10-01T06:00:00"))
    with pytest.raises(ValueError, match="classification"):
        audit.append(**args(dedupe_key="approval", event_type="user_accepted"))
