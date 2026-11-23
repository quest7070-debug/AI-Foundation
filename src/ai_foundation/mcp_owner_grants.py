"""One-shot owner-issued MCP decision delegations in the *existing* Guard DB.

Only the existing CSRF-protected Operator approval surface may issue a grant.
An MCP client can neither issue a grant nor choose another principal. Every
grant identifies the exact Guard request revision, decision, owner-local
principal, and a short expiry. It does not create a new approval level.
"""
from __future__ import annotations

import hmac
import os
from pathlib import Path
import re
import sqlite3
import time

from .store import approval_request_ref

_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_REF = re.compile(r"[a-f0-9]{64}\Z")
_DECISIONS = frozenset({"AUTHORIZE", "DENY"})
_PRINCIPAL = "macos-owner-local"
_SCHEMA = """CREATE TABLE IF NOT EXISTS mcp_owner_delegations (
  run_id TEXT PRIMARY KEY,
  request_ref TEXT NOT NULL,
  decision TEXT NOT NULL,
  principal_id TEXT NOT NULL,
  expires_at REAL NOT NULL,
  consumed INTEGER NOT NULL DEFAULT 0
)"""


class McpOwnerGrants:
    """Issue only in the trusted Operator. Read and claim in MCP host.

    No new DB, external account, background monitor or arbitrary action.
    The absence of the table grants no authority.
    """

    def __init__(self, guard_store, *, initialize=False, now=time.time):
        self.store = guard_store
        self.now = now
        path = Path(guard_store.path)
        if not path.is_file() or path.is_symlink():
            raise ValueError("EXISTING_GUARD_REQUIRED")
        stat = path.stat()
        if stat.st_uid != os.getuid() or stat.st_mode & 0o022:
            raise PermissionError("GUARD_OWNERSHIP_INVALID")
        if initialize:
            # Only the trusted Operator's normal startup may add this table.
            with self.store._connect() as db:
                db.execute(_SCHEMA)

    @staticmethod
    def _ref(db, run_id):
        row = db.execute(
            "SELECT action,target,request_nonce,canon_revision,effect_id "
            "FROM approval_requests WHERE run_id=?", (run_id,)
        ).fetchone()
        return (approval_request_ref(run_id, *row)
                if row and row[2] and row[3] and row[4] else None)

    @staticmethod
    def _valid(run_id, request_ref, decision):
        return (type(run_id) is str and bool(_RUN.fullmatch(run_id))
                and type(request_ref) is str and bool(_REF.fullmatch(request_ref))
                and type(decision) is str and decision in _DECISIONS)

    def issue(self, run_id, request_ref, decision):
        """Called only from Operator's existing authenticated decision UI."""
        if not self._valid(run_id, request_ref, decision):
            return False
        self.store._require_write("MCP owner delegation")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._ref(db, run_id)
            if (not current or not hmac.compare_digest(current, request_ref)
                    or db.execute("SELECT 1 FROM approvals WHERE run_id=?",
                                  (run_id,)).fetchone()
                    or db.execute("SELECT 1 FROM cancellations WHERE run_id=?",
                                  (run_id,)).fetchone()):
                return False
            # No periodic maintenance: retire old one-shot grants during the
            # next explicit owner delegation only. Exact Guard authority stays
            # preserved in its canonical tables.
            db.execute(
                "DELETE FROM mcp_owner_delegations "
                "WHERE consumed=1 OR expires_at<=?", (self.now(),))
            db.execute(
                "INSERT INTO mcp_owner_delegations "
                "(run_id,request_ref,decision,principal_id,expires_at,consumed) "
                "VALUES(?,?,?,?,?,0) ON CONFLICT(run_id) DO UPDATE SET "
                "request_ref=excluded.request_ref,decision=excluded.decision,"
                "principal_id=excluded.principal_id,expires_at=excluded.expires_at,"
                "consumed=0",
                (run_id, request_ref, decision, _PRINCIPAL, self.now()+300),
            )
            return True

    def _active(self, db, run_id, *, tool, principal_id):
        if principal_id != _PRINCIPAL:
            return False
        now = self.now()
        if tool == "approval_requests" and run_id == "":
            rows = db.execute(
                "SELECT run_id,request_ref FROM mcp_owner_delegations "
                "WHERE principal_id=? AND consumed=0 AND expires_at>? LIMIT 101",
                (principal_id, now),
            ).fetchall()
            return bool(rows) and any(
                self._ref(db, run) == ref for run, ref in rows
            )
        if type(run_id) is not str or not _RUN.fullmatch(run_id):
            return False
        row = db.execute(
            "SELECT request_ref,decision FROM mcp_owner_delegations "
            "WHERE run_id=? AND principal_id=? AND consumed=0 AND expires_at>?",
            (run_id, principal_id, now),
        ).fetchone()
        if not row or self._ref(db, run_id) != row[0]:
            return False
        return (tool in {"approval_requests", "review_candidate"}
                or tool == "submit_decision:" + row[1])

    def authorize(self, principal, tool, run_id):
        # A session in McpHostAuthorizer is necessary but never sufficient.
        if tool == "foundation_status":
            return True
        try:
            # No schema initialization and no mutation during regular read.
            with sqlite3.connect("file:"+str(Path(self.store.path).resolve())+"?mode=ro",
                                 uri=True, timeout=3) as db:
                return self._active(db, run_id, tool=tool,
                                    principal_id=principal.principal_id)
        except (sqlite3.Error, AttributeError, ValueError):
            return False

    def claim(self, principal, run_id, request_ref, decision):
        """Consume exact previously issued owner authority BEFORE Guard CAS.

        If Guard state changes before it commits, the claim remains consumed:
        no retry and no automatic fresh authority.
        """
        if (not self._valid(run_id, request_ref, decision)
                or principal.principal_id != _PRINCIPAL):
            return False
        self.store._require_write("MCP owner delegation consume")
        try:
            with self.store._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT request_ref,decision FROM mcp_owner_delegations "
                    "WHERE run_id=? AND principal_id=? AND consumed=0 AND expires_at>?",
                    (run_id, principal.principal_id, self.now()),
                ).fetchone()
                if (not row or row != (request_ref, decision)
                        or self._ref(db, run_id) != request_ref):
                    return False
                updated = db.execute(
                    "UPDATE mcp_owner_delegations SET consumed=1 "
                    "WHERE run_id=? AND request_ref=? AND decision=? "
                    "AND consumed=0 AND expires_at>?",
                    (run_id, request_ref, decision, self.now()),
                )
                return updated.rowcount == 1
        except sqlite3.Error:
            return False
