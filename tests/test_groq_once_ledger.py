"""Groq public E2E claim is durable, global, and at-most-once."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from ai_foundation.groq_once_ledger import INTENT, SQLiteGroqOnceLedger


def claim(ledger, binding="llm:groq:a"):
    return ledger.claim(
        binding=binding, model="openai/gpt-oss-20b",
        endpoint="https://api.groq.com/openai/v1/chat/completions")


def test_first_claim_survives_restart_and_result_loss(tmp_path):
    path = tmp_path / "one.sqlite"
    ledger = SQLiteGroqOnceLedger(path, clock=lambda: 1000)
    assert ledger.status() == "NEVER_CLAIMED"
    assert claim(ledger)
    assert ledger.status() == "CLAIMED_UNCERTAIN"
    reboot = SQLiteGroqOnceLedger(path, clock=lambda: 1001)
    assert reboot.status() == "CLAIMED_UNCERTAIN"
    assert not claim(reboot)
    assert not claim(reboot, "llm:groq:different-key")
    reboot.finish("ONE_SHOT_FAILED")
    assert reboot.status() == "ONE_SHOT_FAILED"
    assert not claim(SQLiteGroqOnceLedger(path), "llm:groq:new-key")


def test_parallel_claims_only_one_dispatch(tmp_path):
    path = tmp_path / "one.sqlite"
    SQLiteGroqOnceLedger(path)  # Creation is not part of the dispatch race.
    def worker(_):
        return claim(SQLiteGroqOnceLedger(path))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = tuple(pool.map(worker, range(8)))
    assert results.count(True) == 1
    assert results.count(False) == 7


def test_terminal_receipt_cannot_be_rewritten_or_reset(tmp_path):
    ledger = SQLiteGroqOnceLedger(tmp_path / "one.sqlite")
    assert claim(ledger)
    ledger.finish("VERIFIED_PUBLIC_FIXTURE")
    assert ledger.status() == "VERIFIED_PUBLIC_FIXTURE"
    ledger.finish("ONE_SHOT_FAILED")
    assert ledger.status() == "VERIFIED_PUBLIC_FIXTURE"
    assert not claim(ledger)
    with pytest.raises(ValueError, match="GROQ_ONCE_OUTCOME_UNSUPPORTED"):
        ledger.finish("UNKNOWN")
    import sqlite3
    with sqlite3.connect(ledger.path) as db:
        row = db.execute(
            "SELECT intent,route_hash,state FROM groq_once_attempt").fetchone()
    assert row[0] == INTENT and row[2] == "TERMINAL"
    assert len(row[1]) == 64
    assert "llm:groq:" not in repr(row)
