"""Durable at-most-once receipt for the fixed Groq public E2E.

A claim is committed before the first transport call. Claiming again is
denied even after timeout, crash, cancellation, failure or process restart:
an uncertain dispatch may already have reached the provider. Do not expire,
retry, reset or recreate these receipts automatically.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time

INTENT = "groq-public-fixture-v1"
_OUTCOMES = frozenset({
    "VERIFIED_PUBLIC_FIXTURE", "NONMATCHING_PUBLIC_FIXTURE",
    "INVALID_PROVIDER_RESPONSE", "ONE_SHOT_FAILED",
})


class SQLiteGroqOnceLedger:
    def __init__(self, path, *, clock=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS groq_once_attempt(
                intent TEXT PRIMARY KEY,
                route_hash TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('CLAIMED','TERMINAL')),
                outcome TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )""")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("PRAGMA busy_timeout=5000")
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _route_hash(binding, model, endpoint):
        return hashlib.sha256(
            ("GROQ\0" + binding + "\0" + model + "\0" + endpoint).encode()
        ).hexdigest()

    def claim(self, *, binding, model, endpoint):
        if not all(type(v) is str and v for v in (binding, model, endpoint)):
            raise ValueError("GROQ_ONCE_ROUTE_IDENTITY_REQUIRED")
        now = float(self.clock())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cur = db.execute("""INSERT OR IGNORE INTO groq_once_attempt
                (intent,route_hash,state,outcome,created_at,updated_at)
                VALUES(?,?,'CLAIMED',NULL,?,?)""", (
                INTENT, self._route_hash(binding, model, endpoint), now, now))
            return cur.rowcount == 1

    def finish(self, outcome):
        if outcome not in _OUTCOMES:
            raise ValueError("GROQ_ONCE_OUTCOME_UNSUPPORTED")
        with self._connect() as db:
            db.execute("""UPDATE groq_once_attempt
                SET state='TERMINAL', outcome=?, updated_at=?
                WHERE intent=? AND state='CLAIMED'""",
                (outcome, float(self.clock()), INTENT))

    def status(self):
        with self._connect() as db:
            row = db.execute(
                "SELECT state,outcome FROM groq_once_attempt WHERE intent=?",
                (INTENT,)).fetchone()
        if not row:
            return "NEVER_CLAIMED"
        return row[1] if row[0] == "TERMINAL" and row[1] else "CLAIMED_UNCERTAIN"
