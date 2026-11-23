"""No-network contract for the manual, fail-closed Free-route admission store."""
import sqlite3

import pytest

from ai_foundation.free_route_admission import SQLiteFreeRouteAdmission


def route(**changes):
    value = {
        "binding": "llm:groq:fixture",
        "provider": "GROQ",
        "tier": "FREE",
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
        "model": "openai/gpt-oss-20b",
        "protocol": "openai-chat",
    }
    value.update(changes)
    return value


def test_free_label_or_existing_legacy_receipt_does_not_auto_grant(tmp_path):
    path = tmp_path / "routes.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE free_route_receipts(binding TEXT)")
        db.execute("INSERT INTO free_route_receipts VALUES ('llm:groq:fixture')")
    gate = SQLiteFreeRouteAdmission(path)
    assert gate.decide(route()).reason == "NOT_MANUALLY_SELECTED"
    with pytest.raises(PermissionError, match="NOT_MANUALLY_SELECTED"):
        gate.require(route(), {"model": route()["model"]})


def test_owner_selected_exact_fixed_free_route_survives_without_timer(tmp_path):
    path = tmp_path / "routes.sqlite"
    gate = SQLiteFreeRouteAdmission(path)
    gate.select(route(), account_alias="account-1", project_alias="project-1")
    assert gate.decide(route()).allowed
    assert gate.verified_scope(route()) is not None
    gate.require(route(), {"model": route()["model"]})
    assert SQLiteFreeRouteAdmission(path).decide(route()).allowed
    for change in (
        {"model": "auto"},
        {"model": "other-model"},
        {"endpoint": "https://different.invalid/"},
        {"binding": "llm:groq:other"},
        {"tier": "PAID"},
    ):
        assert not gate.decide(route(**change)).allowed
    gate.revoke(route()["binding"])
    assert not gate.decide(route()).allowed


@pytest.mark.parametrize("change", [
    {"tier": "PAID"},
    {"model": "auto"},
    {"model": "openrouter/free"},
    {"endpoint": "http://insecure.invalid/"},
])
def test_manual_selection_requires_fixed_nonchargeable_route(tmp_path, change):
    gate = SQLiteFreeRouteAdmission(tmp_path / "routes.sqlite")
    with pytest.raises(ValueError):
        gate.select(route(**change))


def test_no_model_override_or_unpriced_tools(tmp_path):
    gate = SQLiteFreeRouteAdmission(tmp_path / "routes.sqlite")
    gate.select(route())
    with pytest.raises(PermissionError, match="MODEL_OVERRIDE"):
        gate.require(route(), {"model": "other"})
    with pytest.raises(PermissionError, match="UNPRICED_PROVIDER_TOOLS"):
        gate.require(route(), {"model": route()["model"], "tools": [{"type": "web_search"}]})
