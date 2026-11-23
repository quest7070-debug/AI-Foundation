"""Bounded memory-only replay of a HumanModel SQLite backup snapshot.

This does NOT create a durable backup, erase user data, or authorize a restore.
Only the existing authenticated owner process can invoke this against a private
already-open SQLite connection. No source text, ID, path or content hash leaves.
"""
from __future__ import annotations
import sqlite3

from human_model_management_audit import audit_ledger

_MAX_BYTES = 32 * 1024 * 1024


def verify_recovery_copy(db: sqlite3.Connection) -> dict:
    """Independently read back all structural/withdrawal state from a copy."""
    receipt = {"status": "RESTORE_UNAVAILABLE", "execution_authority": False,
               "durable_backup_created": False, "physical_erasure_proven": False}
    if not isinstance(db, sqlite3.Connection):
        return receipt
    copy = None
    try:
        pages = db.execute("PRAGMA page_count").fetchone()[0]
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        if (type(pages) is not int or type(page_size) is not int
                or pages * page_size > _MAX_BYTES):
            return {**receipt, "status": "RESTORE_DRILL_RESOURCE_LIMIT"}
        before = audit_ledger(db)
        if before["status"] not in {
                "STRUCTURE_OK_SOURCE_UNVERIFIED", "REVIEW_REQUIRED"}:
            return {**receipt, "status": "RESTORE_DRILL_SOURCE_INVALID"}
        copy = sqlite3.connect(":memory:")
        # SQLite backup API takes a consistent snapshot; temporary recovered
        # image stays in process memory and is discarded at function exit.
        db.backup(copy, pages=256, sleep=0.01)
        after = audit_ledger(copy)
        if before != after:
            return {**receipt, "status": "RESTORE_DRILL_MISMATCH"}
        return {**receipt, "status": "RESTORE_STRUCTURE_VERIFIED",
                "record_count": before["records"],
                "withdrawn_count": before["withdrawn_sources"],
                "source_stale_count": before["source_stale_count"]}
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return receipt
    finally:
        if copy is not None:
            copy.close()
