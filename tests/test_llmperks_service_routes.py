"""No-network service-to-model discovery integration acceptance."""
import copy

import pytest

from ai_foundation.llmperks_discovery import SourceInvalid
from ai_foundation.llmperks_ranking import FULL_URL, parse_full_dump
from ai_foundation.llmperks_service_routes import (
    project_service_model_routes, research_projection_note,
)

LEDGER = {
    "deployment_state": "RESEARCH_ONLY",
    "default_route_enabled": False,
    "services": [
        {"id": "groq", "name": "Groq API Free", "route_kind": "INFERENCE_API", "enabled": False},
        {"id": "opencode-zen-free", "name": "OpenCode Zen free", "route_kind": "DEVELOPMENT_TOOL",
         "enabled": False},
        {"id": "openrouter", "name": "OpenRouter :free", "route_kind": "INFERENCE_API",
         "enabled": False},
    ],
}
SOURCE = b"""# LLM Perks \xe2\x80\x94 full data dump
# Generated: 2026-11-09T21:54:44.501Z
# Snapshot: 2026-11-09T21:53:10.556Z
# Source: https://llmperks.com
# \xe2\x95\x90\xe2\x95\x90\xe2\x95\x90 Free models \xe2\x95\x90\xe2\x95\x90\xe2\x95\x90

## Same Model
URL: https://llmperks.com/example/same-model
Developer: Example
Type: text; size class: TOP; capabilities: reasoning, coding
AA Intelligence Index: 41.8; GPQA Diamond: 91.2%
- groq: id=example/model; context=123456; url=https://example.org/model
- opencode: id=example/model-free; context=n/a; url=https://example.org/zen
- together: id=example/model; context=123456; url=https://example.org/api

## Other Model
URL: https://llmperks.com/example/other-model
Type: text; size class: MID; capabilities: reasoning
- openrouter: id=example/other:free; context=4096; url=https://example.org/models

# Total: 2 models, 4 free endpoints, 4 providers online
""".replace(b"# \xe2\x95\x90\xe2\x95\x90\xe2\x95\x90 Free models \xe2\x95\x90\xe2\x95\x90\xe2\x95\x90", "# ═══ Free models ═══".encode())


def test_models_group_under_existing_service_without_adding_services():
    catalog = parse_full_dump(SOURCE)
    ledger_before = copy.deepcopy(LEDGER)
    routes = project_service_model_routes(LEDGER, catalog)
    assert routes["provider_model_records"] == 4
    assert routes["direct_api_research_routes"] == 2
    assert routes["non_api_service_observations"] == 1
    assert routes["unmatched_provider_records"] == 1
    assert set(routes["matched_existing_services"]) == {"groq", "openrouter"}
    assert set(routes["existing_non_api_services"]) == {"opencode-zen-free"}
    assert set(routes["unmatched_provider_slugs"]) == {"together"}
    assert routes["execution_authorized"] is False
    assert routes["authority"] == "READ_ONLY_RESEARCH_NOT_A_PROVIDER_OR_ROUTE_REGISTRY"
    assert LEDGER == ledger_before
    for group in routes["matched_existing_services"].values():
        for child in group["research_only_routes"]:
            assert child["runtime_route_enabled"] is False
            assert child["auto_billing_disabled_verified"] is False
            assert child["account_free_verified"] is False


def test_an_exact_registry_id_match_is_only_an_observation():
    catalog = parse_full_dump(SOURCE)
    creds = (
        {"binding": "existing", "provider": "GROQ", "model": "example/model", "tier": "PAID"},
        {"binding": "different", "provider": "OPENROUTER", "model": "example/something-else",
         "tier": "FREE"},
    )
    projection = project_service_model_routes(LEDGER, catalog, credentials=creds)
    groq = projection["matched_existing_services"]["groq"]["research_only_routes"][0]
    op = projection["matched_existing_services"]["openrouter"]["research_only_routes"][0]
    assert groq["registered_model_id_match_only"] is True
    assert groq["runtime_route_enabled"] is False
    assert op["registered_model_id_match_only"] is False
    assert "binding" not in str(projection)


def test_no_fuzzy_mapping_and_deactivated_service_ledger_is_rejected():
    catalog = parse_full_dump(SOURCE)
    partial = copy.deepcopy(LEDGER)
    partial["services"][0]["id"] = "groq-other"
    projection = project_service_model_routes(partial, catalog)
    assert "groq" in projection["unmatched_provider_slugs"]
    partial["services"][0]["enabled"] = True
    with pytest.raises(SourceInvalid, match="INVALID_EXISTING_SERVICE_ENTRY"):
        project_service_model_routes(partial, catalog)


def test_ambiguous_model_provider_identity_is_not_merged_across_models():
    catalog = parse_full_dump(SOURCE)
    polluted = copy.deepcopy(catalog)
    polluted["models"]["https://llmperks.com/example/other-model"]["endpoints_claimed"].append(
        {"provider": "groq", "provider_model_id_claimed": "example/model"})
    polluted["publisher_totals_not_verified"]["endpoints"] += 1
    with pytest.raises(SourceInvalid, match="AMBIGUOUS_PROVIDER_MODEL_ID"):
        project_service_model_routes(LEDGER, polluted)


def test_notes_are_concise_non_execution_authority():
    catalog = parse_full_dump(SOURCE)
    note = research_projection_note(project_service_model_routes(LEDGER, catalog))
    assert "groq: 1" in note
    assert "Unmatched together: 1" in note
    assert "OpenCode" not in note  # no fake direct API route registration
    assert "disabled" in note
    assert "example/model" not in note  # no credential or model-ID leak in note
    assert len(note.encode()) < 8192


def test_research_service_kind_never_invents_native_adapter():
    catalog = copy.deepcopy(parse_full_dump(SOURCE))
    ledger = copy.deepcopy(LEDGER)
    ledger["services"].append({
        "id": "cloudflare", "name": "Workers AI API", "route_kind": "INFERENCE_API",
        "enabled": False,
    })
    model = catalog["models"]["https://llmperks.com/example/same-model"]
    model["endpoints_claimed"].append({
        "provider": "cloudflare", "provider_model_id_claimed": "@cf/example/model",
        "context_claimed": "10000",
    })
    catalog["publisher_totals_not_verified"]["endpoints"] += 1
    result = project_service_model_routes(ledger, catalog)
    group = result["matched_existing_services"]["cloudflare"]
    assert group["route_kind"] == "INFERENCE_API"
    assert group["known_foundation_adapter"] is False
    assert group["research_only_routes"][0]["known_foundation_adapter"] is False
    assert result["existing_adapter_model_mentions"] == 2
    assert result["research_api_service_without_adapter"] == 1
    assert group["research_only_routes"][0]["runtime_route_enabled"] is False
