"""One manual owner action; no automatic service or billing workflow."""
import importlib.util
import json
from pathlib import Path

import pytest

from ai_foundation.provider_registry import SQLiteProviderRegistry
from ai_foundation.free_route_admission import SQLiteFreeRouteAdmission


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/manual_free_service.py"
spec = importlib.util.spec_from_file_location("manual_free_service", SCRIPT)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def setup(tmp_path):
    db = SQLiteProviderRegistry(tmp_path / "providers.sqlite")
    db.upsert("manual:groq", "GROQ", tier="FREE", health="UNVERIFIED",
              endpoint="https://api.groq.com/openai/v1/chat/completions",
              model="openai/gpt-oss-20b", protocol="openai-chat")
    db.upsert("manual:paid", "GROQ", tier="PAID", health="ONLINE",
              endpoint="https://api.groq.com/openai/v1/chat/completions",
              model="openai/gpt-oss-20b", protocol="openai-chat")
    return db


def test_manual_selection_persists_and_revoke_has_no_network(tmp_path, capsys):
    registry = setup(tmp_path)
    common = ["--root", str(tmp_path)]
    gate = SQLiteFreeRouteAdmission(tmp_path / "free-route-admission.sqlite")
    meta = registry.credential("manual:groq")
    assert gate.decide(meta).reason == "NOT_MANUALLY_SELECTED"

    subject.main(common + ["list"])
    listed = json.loads(capsys.readouterr().out)
    assert listed["mode"] == "MANUAL_ONLY"
    assert all(not x["selected"] for x in listed["services"])

    with pytest.raises(SystemExit):
        subject.main(common + ["select", "--binding", "manual:groq"])
    assert not gate.decide(meta).allowed

    subject.main(common + ["select", "--binding", "manual:groq",
                           "--confirm-no-auto-charge"])
    assert json.loads(capsys.readouterr().out)["selected"]
    assert SQLiteFreeRouteAdmission(tmp_path / "free-route-admission.sqlite").decide(meta).allowed

    subject.main(common + ["revoke", "--binding", "manual:groq"])
    assert not gate.decide(meta).allowed


def test_paid_and_credential_identity_changes_cannot_use_selection(tmp_path):
    registry = setup(tmp_path)
    gate = SQLiteFreeRouteAdmission(tmp_path / "free-route-admission.sqlite")
    with pytest.raises(ValueError, match="NOT_FREE_TIER"):
        gate.select(registry.credential("manual:paid"))
    meta = registry.credential("manual:groq")
    gate.select(meta)
    assert gate.decide(meta).allowed
    assert gate.decide({**meta, "model": "other-model"}).reason == "ROUTE_IDENTITY_CHANGED"
    assert gate.decide({**meta, "endpoint": "https://other.test"}).reason == "ROUTE_IDENTITY_CHANGED"


def test_old_billing_receipts_never_activate_manual_selection(tmp_path):
    import sqlite3
    with sqlite3.connect(tmp_path / "free-route-admission.sqlite") as db:
        db.execute("CREATE TABLE free_route_receipts(binding TEXT PRIMARY KEY)")
        db.execute("INSERT INTO free_route_receipts VALUES('manual:groq')")
    registry = setup(tmp_path)
    gate = SQLiteFreeRouteAdmission(tmp_path / "free-route-admission.sqlite")
    assert gate.decide(registry.credential("manual:groq")).reason == "NOT_MANUALLY_SELECTED"
