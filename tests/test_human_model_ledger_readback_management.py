"""Existing read-only M1 ledger verifier + model-free management receipt.

Tests exercise only synthetic SQLite paths. No real volume or private source
is opened, no model/tool call is made, and nothing is initialized on read.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "experiments" / "human_model"))

import human_model_ledger_verify as readback
import storage_location
from human_model_ledger import Ledger


def test_m1_readback_keeps_private_source_out_of_json(monkeypatch, tmp_path):
    path = tmp_path / "human_model.sqlite3"
    text = "SYNTHETIC-PRIVATE-NOT-FOR-RECEIPTS"
    ledger = Ledger(path)
    try:
        ledger.add(source_uri="synthetic-owner:message-1", source_revision="1",
                   kind="observation", scope="work", privacy="private",
                   content=text, observed_at=None)
        ledger.define_view(view_id="work", purpose="synthetic",
                           audience="foundation", allowed_scopes=["work"])
        ledger.rebuild_view(view_id="work")
    finally:
        ledger.close()
    monkeypatch.setattr(readback, "select_mount", lambda: tmp_path)
    monkeypatch.setattr(storage_location, "validated_ledger_path", lambda _: path)

    result = readback.verify()
    assert result["external_usb"] is True  # simulated trusted mount in fixture
    assert result["read_only"] is True
    assert result["evidence_count"] == 1
    assert result["human_model_management"]["status"] == "STRUCTURE_OK_SOURCE_UNVERIFIED"
    safe = json.dumps(result)
    assert text not in safe and "synthetic-owner" not in safe
    assert hashlib.sha256(text.encode()).hexdigest() not in safe
    ledger = Ledger(path)
    try:
        assert ledger.db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
    finally:
        ledger.close()


def test_m1_readback_reports_hash_damage_without_raw_source(monkeypatch, tmp_path):
    path = tmp_path / "human_model.sqlite3"
    ledger = Ledger(path)
    try:
        eid = ledger.add(source_uri="synthetic:message", source_revision="1",
                         kind="observation", scope="work", privacy="private",
                         content="ORIGINAL-SECRET-SYNTHETIC")
        with ledger.db:
            ledger.db.execute("UPDATE evidence SET content=? WHERE id=?",
                              ("MUTATED-PRIVATE-SYNTHETIC", eid))
    finally:
        ledger.close()
    monkeypatch.setattr(readback, "select_mount", lambda: tmp_path)
    monkeypatch.setattr(storage_location, "validated_ledger_path", lambda _: path)
    result = readback.verify()
    audit = result["human_model_management"]
    assert audit["status"] == "STRUCTURE_INVALID"
    assert audit["hash_mismatches"] == 1
    assert "MUTATED-PRIVATE-SYNTHETIC" not in json.dumps(result)
