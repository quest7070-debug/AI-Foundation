"""Research-only model-route children under the EXISTING service ledger.

A model is not an account/provider service. The same model can have several
provider-specific model IDs. Publisher "free" claims cannot create a credential,
manual selection, billable endpoint, route, or registry entry. This projection
does not read any credentials or touch Foundation's runtime route database.
"""
from __future__ import annotations

from .llmperks_discovery import SourceInvalid
from .llmperks_ranking import FULL_URL
from .external_service_inventory import _DIRECT_PROVIDERS

# Exact reviewed IDs from docs/data/free_ai_route_candidates_20261109.json.
# This is deliberately NOT derived by fuzzy company-name similarity.
_PROVIDER_SERVICE = {
    "groq": "groq",
    "openrouter": "openrouter",
    "gemini": "gemini-api",
    "nvidia": "nvidia",
    "cloudflare": "cloudflare",
    "cohere": "cohere",
    "opencode": "opencode-zen-free",  # CLI/gateway, NOT direct inference API.
}

# The existing credentials registry provider fields are separate from publisher
# provider slugs. This mapping is for an optional READ-ONLY model-ID comparison.
_REGISTRY_PROVIDER = {
    "groq": "GROQ",
    "openrouter": "OPENROUTER",
    "gemini": "GEMINI",
    "nvidia": "NVIDIA",
    "cloudflare": "CLOUDFLARE",
    "cohere": "COHERE",
}


def _existing_services(ledger):
    if (type(ledger) is not dict or ledger.get("deployment_state") != "RESEARCH_ONLY"
            or ledger.get("default_route_enabled") is not False
            or type(ledger.get("services")) is not list):
        raise SourceInvalid("INVALID_EXISTING_SERVICE_LEDGER")
    services = {}
    for row in ledger["services"]:
        if (type(row) is not dict or type(row.get("id")) is not str
                or not row["id"] or row["id"] in services
                or row.get("enabled") is not False
                or type(row.get("route_kind")) is not str):
            raise SourceInvalid("INVALID_EXISTING_SERVICE_ENTRY")
        services[row["id"]] = row
    return services


def _registered_ids(credentials):
    """Exact model-ID equality only. No fuzzy provider/model equivalence."""
    ids = set()
    for row in credentials:
        if (type(row) is dict and type(row.get("provider")) is str
                and type(row.get("model")) is str and row.get("binding")):
            ids.add((row["provider"].upper(), row["model"]))
    return ids


def project_service_model_routes(ledger, full_catalog, *, credentials=()):
    """Read-only join from publisher model data to existing service identities.

    - Direct API services get non-executable research child routes.
    - OpenCode is categorized under its existing *tool* service but not
      misrepresented as Foundation's native direct API.
    - A publisher provider without an existing reviewed service stays unmatched.
    - A matching registered credential model ID is a string observation only;
      it is NOT proof of current credentials, free tier, manual selection,
      provider availability, or billing safety.
    """
    services = _existing_services(ledger)
    if (type(full_catalog) is not dict
            or full_catalog.get("schema") != "llmperks-full-claims-v1"
            or full_catalog.get("source_url") != FULL_URL
            or full_catalog.get("authority") != "RESEARCH_ONLY_NO_EXECUTION_OR_BILLING"
            or type(full_catalog.get("models")) is not dict):
        raise SourceInvalid("INVALID_RESEARCH_CATALOG")
    registry_ids = _registered_ids(credentials)
    children = {}
    unmatched = {}
    special = {}
    seen = {}
    count = 0
    existing_adapter_count = 0
    for model_page, model in full_catalog["models"].items():
        if (type(model_page) is not str or type(model) is not dict
                or model.get("model_page") != model_page
                or type(model.get("endpoints_claimed")) is not list
                or type(model.get("name")) is not str
                or type(model.get("reasoning")) is not bool):
            raise SourceInvalid("INVALID_MODEL_RECORD")
        for endpoint in model["endpoints_claimed"]:
            if (type(endpoint) is not dict
                    or type(endpoint.get("provider")) is not str
                    or type(endpoint.get("provider_model_id_claimed")) is not str):
                raise SourceInvalid("INVALID_PROVIDER_MODEL_ID")
            slug = endpoint["provider"]
            model_id = endpoint["provider_model_id_claimed"]
            if not slug or not model_id:
                raise SourceInvalid("EMPTY_PROVIDER_MODEL_ID")
            identity = (slug, model_id)
            if identity in seen:
                raise SourceInvalid("AMBIGUOUS_PROVIDER_MODEL_ID")
            seen[identity] = model_page
            count += 1
            service_id = _PROVIDER_SERVICE.get(slug)
            service = services.get(service_id) if service_id else None
            direct = service is not None and service.get("route_kind") == "INFERENCE_API"
            adapter_present = bool(direct and service_id in _DIRECT_PROVIDERS)
            if adapter_present:
                existing_adapter_count += 1
            display = {
                "model": model["name"],
                "model_page": model_page,
                "provider_slug": slug,
                "provider_model_id_claimed": model_id,
                "reasoning_claimed": model["reasoning"],
                "aa_intelligence_claimed": model.get("aa_intelligence"),
                "gpqa_diamond_claimed": model.get("gpqa_diamond"),
                "known_foundation_adapter": adapter_present,
                "registered_model_id_match_only": (
                    adapter_present and (_REGISTRY_PROVIDER.get(slug), model_id) in registry_ids),
                "status": "DISCOVERED_UNVERIFIED_NOT_EXECUTABLE",
                "account_free_verified": False,
                "auto_billing_disabled_verified": False,
                "runtime_route_enabled": False,
            }
            if direct:
                children.setdefault(service_id, []).append(display)
            elif service:
                # OpenCode's discovery is a CLI/gateway candidate, not an API
                # credential route from the dedicated inference adapter.
                special.setdefault(service_id, []).append(display)
            else:
                unmatched.setdefault(slug, []).append(display)

    declared = full_catalog.get("publisher_totals_not_verified")
    if (type(declared) is not dict or type(declared.get("endpoints")) is not int
            or count != declared["endpoints"]):
        raise SourceInvalid("ROUTE_COUNT_MISMATCH")
    sorter = lambda row: (
        0 if row["reasoning_claimed"] else 1,
        -(row["aa_intelligence_claimed"] or -1),
        -(row["gpqa_diamond_claimed"] or -1),
        row["model_page"], row["provider_model_id_claimed"],
    )
    for grouping in (children, special, unmatched):
        for rows in grouping.values():
            rows.sort(key=sorter)

    return {
        "schema": "foundation-service-model-research-projection-v1",
        "source_url": FULL_URL,
        "publisher_snapshot": full_catalog["publisher_snapshot"],
        "source_sha256": full_catalog["sha256"],
        "existing_service_ledger_unchanged": True,
        "provider_model_records": count,
        "direct_api_research_routes": sum(map(len, children.values())),
        "existing_adapter_model_mentions": existing_adapter_count,
        "research_api_service_without_adapter": sum(map(len, children.values())) - existing_adapter_count,
        "non_api_service_observations": sum(map(len, special.values())),
        "unmatched_provider_records": sum(map(len, unmatched.values())),
        "matched_existing_services": {
            sid: {
                "service_id": sid,
                "service_name": services[sid]["name"],
                "route_kind": services[sid]["route_kind"],
                "known_foundation_adapter": sid in _DIRECT_PROVIDERS,
                "research_only_routes": children[sid],
            } for sid in sorted(children)
        },
        "existing_non_api_services": {
            sid: {
                "service_id": sid,
                "route_kind": services[sid]["route_kind"],
                "research_only_model_mentions": special[sid],
            } for sid in sorted(special)
        },
        "unmatched_provider_slugs": {
            slug: unmatched[slug] for slug in sorted(unmatched)
        },
        "authority": "READ_ONLY_RESEARCH_NOT_A_PROVIDER_OR_ROUTE_REGISTRY",
        "execution_authorized": False,
    }


def research_projection_note(projection):
    """Compact digest for owner/Drive review, without secrets or service mutation."""
    if projection.get("schema") != "foundation-service-model-research-projection-v1":
        raise SourceInvalid("INVALID_ROUTE_PROJECTION")
    lines = [
        "# LLMPerks model API routes by existing Foundation service (research only)",
        "Publisher snapshot: " + projection["publisher_snapshot"],
        "Endpoint claims observed: " + str(projection["provider_model_records"]),
        "Linked to existing API research service: " + str(projection["direct_api_research_routes"]),
        "Of those, known Foundation adapter model mentions: " + str(projection["existing_adapter_model_mentions"]),
        "API research service without current native adapter: " + str(projection["research_api_service_without_adapter"]),
        "Linked to existing non-API tool service: " + str(projection["non_api_service_observations"]),
        "Provider has no suitable existing service entry: " + str(projection["unmatched_provider_records"]),
        "All rows remain unverified, disabled and cannot create runtime routes.",
        "An affiliate/model page URL is not an executable API base URL.",
    ]
    for sid, row in projection["matched_existing_services"].items():
        lines.append("- " + sid + ": " + str(len(row["research_only_routes"])) + " observed model/API IDs")
    for sid, row in projection["existing_non_api_services"].items():
        lines.append("- " + sid + ": " + str(len(row["research_only_model_mentions"])) + " tool-only model mentions")
    for slug, rows in projection["unmatched_provider_slugs"].items():
        lines.append("- Unmatched " + slug + ": " + str(len(rows)) + " model/API IDs")
    return "\n".join(lines) + "\n"
