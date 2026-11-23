"""No-network acceptance for service-level management projection."""
import json
from pathlib import Path

import pytest

from ai_foundation.external_service_inventory import service_inventory


ROOT = Path(__file__).resolve().parents[1]
LEDGER = json.loads((ROOT / "docs/data/free_ai_route_candidates_20261109.json").read_text())


class Admission:
    def __init__(self, accepted):
        self.accepted = set(accepted)

    def decide(self, row):
        from types import SimpleNamespace
        return SimpleNamespace(allowed=row.get("binding") in self.accepted)


def get(rows, sid):
    return next(x for x in rows if x.service_id == sid)


def test_all_research_services_are_represented_once_and_none_is_auto_enabled():
    inventory = service_inventory(LEDGER)
    assert len(inventory) == 42
    assert {x.service_id for x in inventory} == {x["id"] for x in LEDGER["services"]}
    assert all(x.approved_route_count == 0 and x.billing_state == "NOT_ADMITTED"
               and x.connection_state == "NOT_CONNECTED" for x in inventory)


def test_groq_service_groups_multiple_keys_without_exposing_identity_or_secrets():
    registered = (
        {"binding": "llm:groq:a", "provider": "GROQ", "tier": "FREE",
         "model": "openai/gpt-oss-20b", "health": "ONLINE"},
        {"binding": "llm:groq:b", "provider": "GROQ", "tier": "FREE",
         "model": "openai/gpt-oss-20b", "health": "UNVERIFIED"},
    )
    inventory = service_inventory(LEDGER, credentials=registered,
                                  secret_available=lambda key: key.endswith(":a"),
                                  free_route=Admission(("llm:groq:a",)))
    groq = get(inventory, "groq")
    assert groq.credential_count == 2
    assert groq.connection_state == "CREDENTIAL_AVAILABLE"
    assert groq.approved_route_count == 1
    assert groq.models == ("openai/gpt-oss-20b",)
    assert groq.billing_state == "ATTESTED_MODEL_SCOPED"
    assert "llm:groq:a" not in repr(groq) and "llm:groq:b" not in repr(groq)
    assert get(inventory, "jules").credential_count == 0
    assert get(inventory, "opencode-console-free").approved_route_count == 0


def test_api_identity_not_transferred_to_gateway_cli_or_paid_tier():
    registered = (
        {"binding": "llm:groq:paid", "provider": "GROQ", "tier": "PAID",
         "model": "openai/gpt-oss-20b", "health": "ONLINE"},
    )
    inventory = service_inventory(LEDGER, credentials=registered,
                                  secret_available=lambda _: True,
                                  free_route=Admission(("llm:groq:paid",)))
    assert get(inventory, "groq").approved_route_count == 0
    for sid in ("jules", "opencode-console-free", "opencode-zen-free"):
        assert get(inventory, sid).credential_count == 0


def test_missing_keychain_proof_keeps_registered_service_unaccepted():
    registered = (
        {"binding": "llm:groq:abc", "provider": "GROQ", "tier": "FREE",
         "model": "openai/gpt-oss-20b", "health": "ONLINE"},
    )
    rows = service_inventory(LEDGER, credentials=registered,
                             free_route=Admission(("llm:groq:abc",)))
    assert get(rows, "groq").connection_state == "REGISTERED_UNVERIFIED"
    assert get(rows, "groq").approved_route_count == 0


def test_research_cannot_promote_itself_to_execution():
    changed = dict(LEDGER)
    changed["services"] = [dict(x) for x in LEDGER["services"]]
    changed["services"][0]["enabled"] = True
    with pytest.raises(ValueError, match="RESEARCH_LEDGER_MUST_NOT_ENABLE_EXECUTION"):
        service_inventory(changed)
    changed["services"][0]["enabled"] = False
    changed["services"][1]["id"] = changed["services"][0]["id"]
    with pytest.raises(ValueError, match="DUPLICATE_OR_EMPTY_SERVICE_ID"):
        service_inventory(changed)



def test_first_call_on_attested_free_account_does_not_need_online_probe():
    registered = ({
        "binding": "llm:groq:accepted-free", "provider": "GROQ",
        "tier": "FREE", "model": "openai/gpt-oss-20b",
        "health": "UNVERIFIED",
    },)
    entries = service_inventory(
        LEDGER, credentials=registered,
        secret_available=lambda _: True,
        free_route=Admission(("llm:groq:accepted-free",)))
    groq = get(entries, "groq")
    assert groq.approved_route_count == 1
    assert groq.billing_state == "ATTESTED_MODEL_SCOPED"
