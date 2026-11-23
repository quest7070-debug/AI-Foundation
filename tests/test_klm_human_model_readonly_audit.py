"""Existing KLM tick reuses HumanModel structural receipts without 9B."""
import sys
from types import SimpleNamespace

from scripts import klm_drive_host_tick as host


def test_tick_audit_uses_only_existing_readback(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "human_model_ledger_verify",
        SimpleNamespace(verify=lambda: (calls.append("read"),
            {"human_model_management": {
                "status": "STRUCTURE_OK_SOURCE_UNVERIFIED",
                "records": 2, "execution_authority": False}})[1]))
    receipt = host.owner_management_readonly_audit()
    assert receipt["status"] == "STRUCTURE_OK_SOURCE_UNVERIFIED"
    assert receipt["records"] == 2
    assert calls == ["read"]


def test_missing_or_unavailable_owner_volume_never_breaks_klm(monkeypatch):
    def failed():
        raise RuntimeError("SYNTHETIC_PRIVATE_SOURCE_PATH")
    monkeypatch.setitem(sys.modules, "human_model_ledger_verify",
                        SimpleNamespace(verify=failed))
    receipt = host.owner_management_readonly_audit()
    assert receipt == {"status": "HUMAN_MODEL_LEDGER_UNAVAILABLE",
                       "execution_authority": False}
    assert "SYNTHETIC_PRIVATE_SOURCE_PATH" not in str(receipt)


def test_unknown_audit_state_is_not_silently_accepted(monkeypatch):
    monkeypatch.setitem(sys.modules, "human_model_ledger_verify",
                        SimpleNamespace(verify=lambda: {
                            "human_model_management": {
                                "status": "SOURCE_APPROVED_TO_SHARE",
                                "execution_authority": True}}))
    receipt = host.owner_management_readonly_audit()
    assert receipt["status"] == "HUMAN_MODEL_LEDGER_UNAVAILABLE"
    assert receipt["execution_authority"] is False
