"""Read-only service-first inventory over existing research and credential owners.

The service is the management object. Credential bindings and model routes are
child resources, not independent services. Research entries confer no runtime
permission. No parallel provider DB, auto-enrolment, polling or billing API.
"""
from dataclasses import dataclass
from typing import Mapping


# Only direct adapters already provided by Foundation. An agent or cloud
# development service is a distinct integration type, never silently made
# executable because a provider API key happens to exist.
_DIRECT_PROVIDERS = {
    "groq": "GROQ",
    "gemini-api": "GEMINI",
    "openrouter": "OPENROUTER",
    "nvidia": "NVIDIA",
    "cohere": "COHERE",
}


@dataclass(frozen=True)
class ServiceView:
    service_id: str
    name: str
    integration_kind: str
    research_state: str
    connection_state: str
    credential_count: int
    approved_route_count: int
    billing_state: str
    models: tuple[str, ...]


def service_inventory(research: Mapping, *, credentials=(),
                      secret_available=None, free_route=None):
    """Group by service; preserve the 42 disabled research candidates.

    secret_available(binding) is an optional authoritative local Keychain
    presence check. Without it a stored registry binding is NOT proof of
    currently available credentials.
    """
    if research.get("deployment_state") != "RESEARCH_ONLY":
        raise ValueError("UNSUPPORTED_RESEARCH_STATE")
    rows = research.get("services")
    if not isinstance(rows, list):
        raise ValueError("INVALID_SERVICE_LEDGER")
    indexed = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError("INVALID_SERVICE_LEDGER")
        sid = row["id"]
        if not sid or sid in indexed:
            raise ValueError("DUPLICATE_OR_EMPTY_SERVICE_ID")
        if row.get("enabled") is not False:
            raise ValueError("RESEARCH_LEDGER_MUST_NOT_ENABLE_EXECUTION")
        indexed[sid] = row
    # Group credentials by *provider* first, never persist raw key values
    # or serialize binding identities into the service-level display.
    by_provider = {}
    for cred in credentials:
        if isinstance(cred, dict) and cred.get("provider"):
            by_provider.setdefault(str(cred["provider"]).upper(), []).append(cred)
    out = []
    for sid, row in indexed.items():
        route_kind = str(row.get("route_kind") or "UNCLASSIFIED")
        provider = _DIRECT_PROVIDERS.get(sid)
        direct_api = bool(provider and route_kind == "INFERENCE_API")
        # Do not let arbitrary research IDs adopt a live credential by fuzzy
        # matching names. A non-API service has no Foundation API execution
        # adapter, even if it shares an upstream account with Groq etc.
        creds = tuple(by_provider.get(provider, ())) if direct_api else ()
        known = tuple(c for c in creds if c.get("binding"))
        present = tuple(c for c in known if
                        secret_available is not None and
                        secret_available(c["binding"]) is True)
        approved = tuple(c for c in present if free_route is not None
                         and free_route.decide(c).allowed
                         and c.get("health") in ("ONLINE", "UNVERIFIED")
                         and c.get("tier") == "FREE")
        connected = (
            "CREDENTIAL_AVAILABLE" if present else
            "REGISTERED_UNVERIFIED" if known else "NOT_CONNECTED"
        )
        out.append(ServiceView(
            service_id=sid, name=str(row.get("name") or sid),
            integration_kind=route_kind,
            research_state=str(row.get("assessment") or "UNKNOWN"),
            connection_state=connected,
            credential_count=len(known),
            approved_route_count=len(approved),
            billing_state=(
                "ATTESTED_MODEL_SCOPED" if approved else "NOT_ADMITTED"
            ),
            models=tuple(sorted({str(c["model"]) for c in known
                                 if c.get("model")})),
        ))
    return tuple(out)
