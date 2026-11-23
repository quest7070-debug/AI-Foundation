"""Append-only evidence audit journal for local HumanModel Raw Inbox.

This module does not ingest raw text or promote evidence to a personal ledger.
The caller must provide a validated RawInbox on a private mounted volume.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from uuid import uuid4

EVENT_TYPES = frozenset({
    "source_discovered", "gap_opened", "source_verified",
    "attribution_corrected", "contradiction_linked", "gap_resolved",
})
ACTORS = frozenset({"user", "assistant", "automation", "external", "unknown"})
QUALITY = frozenset({"direct", "secondary", "other_chat", "unverified"})
DDL = """
CREATE TABLE IF NOT EXISTS evidence_audit_events (
    event_id TEXT PRIMARY KEY,
    source_raw_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    message_locator TEXT,
    actor TEXT NOT NULL,
    event_type TEXT NOT NULL,
    observed_at TEXT,
    evidence_quality TEXT NOT NULL,
    related_event_ids TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(source_raw_id) REFERENCES raw_items(id)
);
CREATE INDEX IF NOT EXISTS evidence_audit_by_source
ON evidence_audit_events(source_raw_id, created_at);
"""

class EvidenceAudit:
    def __init__(self, inbox):
        self.inbox = inbox
        self.db = inbox.db
        self.db.executescript(DDL)

    def append(self, *, raw_id, digest, source_uri, event_type, actor,
               evidence_quality, dedupe_key, message_locator=None,
               observed_at=None, related_event_ids=()):
        if event_type not in EVENT_TYPES or actor not in ACTORS or evidence_quality not in QUALITY:
            raise ValueError("unsupported audit event classification")
        if not isinstance(dedupe_key, str) or not dedupe_key.strip():
            raise ValueError("dedupe_key required")
        if observed_at is not None:
            dt = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            if dt.tzinfo is None or dt.utcoffset() is None:
                raise ValueError("observed_at must have timezone")
        raw = self.db.execute(
            "SELECT source_uri,content_sha256 FROM raw_items WHERE id=?", (raw_id,)
        ).fetchone()
        if raw is None or raw != (source_uri, digest):
            raise ValueError("source Raw ID/URI/digest mismatch")
        if not isinstance(related_event_ids, (list, tuple)):
            raise ValueError("related_event_ids must be a sequence")
        links = tuple(related_event_ids)
        if any(not isinstance(v, str) or not v for v in links):
            raise ValueError("invalid related event ID")
        if links:
            found = self.db.execute(
                "SELECT event_id FROM evidence_audit_events WHERE event_id IN (" +
                ",".join("?" for _ in links) + ")", links
            ).fetchall()
            if len(found) != len(set(links)):
                raise ValueError("unresolved related event ID")
        payload = (raw_id, digest, source_uri, message_locator, actor, event_type,
                   observed_at, evidence_quality, json.dumps(links), dedupe_key)
        existing = self.db.execute(
            "SELECT source_raw_id,source_sha256,source_uri,message_locator,actor,"
            "event_type,observed_at,evidence_quality,related_event_ids "
            "FROM evidence_audit_events WHERE dedupe_key=?", (dedupe_key,)
        ).fetchone()
        if existing:
            if existing != payload[:-1]:
                raise ValueError("conflicting audit replay")
            return False
        with self.db:
            self.db.execute(
                "INSERT INTO evidence_audit_events "
                "(event_id,source_raw_id,source_sha256,source_uri,message_locator,"
                "actor,event_type,observed_at,evidence_quality,related_event_ids,dedupe_key)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (str(uuid4()), *payload)
            )
        return True

    def list_metadata(self, *, limit=100):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("invalid limit")
        rows = self.db.execute(
            "SELECT event_id,source_raw_id,event_type,evidence_quality,created_at "
            "FROM evidence_audit_events ORDER BY created_at,event_id LIMIT ?", (limit,)
        ).fetchall()
        return [dict(zip(("event_id","raw_id","event_type","quality","created_at"), r))
                for r in rows]
