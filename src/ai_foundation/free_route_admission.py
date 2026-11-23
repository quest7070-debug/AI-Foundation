"""Manual Free-service allowlist used by the trusted Foundation host.

An API key, a FREE label, a research result or a healthy probe cannot approve
service use. Only an explicit owner-selected binding can be enabled.
No account pricing probes, automatic selection, receipt flags, or timed renewal
exist here. Old free_route_receipts records are deliberately NOT migrated:
an old billing attestation must never silently become an owner selection.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import sqlite3
import unicodedata

_DYNAMIC_MODELS = frozenset({"auto", "latest", "free", "openrouter/free", "kilo-auto/free"})
# Pool/router aliases may be namespaced. These never pin a single billable
# model even when a caller labels the route FREE, so a manual selection alone
# must not allow them. A fixed model ending in :free is intentionally allowed.
_DYNAMIC_SUFFIXES = ("/auto", "/latest", "/free", "-latest",
                     ":auto", ":latest", "@auto", "@latest")


def fixed_model(model):
    if (type(model) is not str or not 1 <= len(model) <= 160
            or any(c.isspace() or unicodedata.category(c) in ("Cc", "Cf")
                   for c in model) or "*" in model):
        return False
    normalized = model.lower()
    # A :free price suffix does not make a provider-controlled auto pool a
    # pinned model. Evaluate the underlying alias before admitting the route.
    identity = normalized[:-5] if normalized.endswith(":free") else normalized
    return identity not in _DYNAMIC_MODELS and not identity.endswith(_DYNAMIC_SUFFIXES)


@dataclass(frozen=True)
class FreeRouteDecision:
    allowed: bool
    reason: str


class SQLiteFreeRouteAdmission:
    """Persistent manual selection; old class name retained for callers.

    Only trusted host/operator code may call select(). AI/tool/research data
    must never have write access to this store. No periodic job updates it.
    """

    def __init__(self, path, *, storage_admission=None, clock=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_admission = storage_admission
        # clock is accepted for existing constructor callers; not used.
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS manually_selected_free_routes(
                binding TEXT PRIMARY KEY, provider TEXT NOT NULL,
                endpoint TEXT NOT NULL, model TEXT NOT NULL,
                account_alias TEXT NOT NULL, project_alias TEXT NOT NULL)""")

    def _write(self):
        if self.storage_admission:
            self.storage_admission.require("manual Free service selection")

    def select(self, meta, *, account_alias="", project_alias=""):
        """Record a *human's* selection of a non-chargeable Free service.

        meta must come from the actual credential registry, not from the
        AI or a provider response. The human must have checked that this
        account and provider cannot automatically charge money; this
        method does not claim to verify the provider's payment settings.
        The optional aliases only group known keys for service display.
        """
        if type(meta) is not dict:
            raise TypeError("REGISTERED_CREDENTIAL_REQUIRED")
        binding, provider = meta.get("binding"), meta.get("provider")
        endpoint, model = meta.get("endpoint"), meta.get("model")
        if meta.get("tier") != "FREE":
            raise ValueError("NOT_FREE_TIER")
        if (any(type(v) is not str or not v or len(v) > 160
                for v in (binding, provider))
                or type(endpoint) is not str or not endpoint.startswith("https://")
                or not fixed_model(model)):
            raise ValueError("INVALID_MANUAL_FREE_ROUTE")
        if (type(account_alias) is not str or type(project_alias) is not str
                or len(account_alias) > 160 or len(project_alias) > 160
                or bool(account_alias) != bool(project_alias)):
            raise ValueError("INVALID_MANUAL_SCOPE")
        self._write()
        with sqlite3.connect(self.path) as db:
            db.execute("""INSERT OR REPLACE INTO manually_selected_free_routes
                (binding,provider,endpoint,model,account_alias,project_alias)
                VALUES(?,?,?,?,?,?)""", (
                binding, provider.upper(), endpoint, model,
                account_alias, project_alias))

    def revoke(self, binding):
        self._write()
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM manually_selected_free_routes WHERE binding=?", (binding,))

    def decide(self, meta):
        if not isinstance(meta, dict) or not meta.get("binding"):
            return FreeRouteDecision(False, "NO_BINDING")
        if meta.get("tier") != "FREE":
            return FreeRouteDecision(False, "NOT_FREE_TIER")
        if not fixed_model(meta.get("model")) or not meta.get("endpoint"):
            return FreeRouteDecision(False, "DYNAMIC_OR_UNBOUND_MODEL")
        with sqlite3.connect(self.path) as db:
            row = db.execute("""SELECT provider,endpoint,model
                FROM manually_selected_free_routes WHERE binding=?""",
                (meta["binding"],)).fetchone()
        if row is None:
            return FreeRouteDecision(False, "NOT_MANUALLY_SELECTED")
        provider, endpoint, model = row
        if (provider != str(meta.get("provider") or "").upper()
                or endpoint != meta.get("endpoint") or model != meta.get("model")):
            return FreeRouteDecision(False, "ROUTE_IDENTITY_CHANGED")
        return FreeRouteDecision(True, "MANUALLY_SELECTED_FREE_ROUTE")

    def verified_scope(self, meta):
        """Group manually identified account/project aliases, never secrets.

        A selected binding with unknown account/project scope remains
        anonymous; unrelated keys must not be merged by provider name.
        """
        if not self.decide(meta).allowed:
            return None
        with sqlite3.connect(self.path) as db:
            row = db.execute("""SELECT account_alias,project_alias
                FROM manually_selected_free_routes WHERE binding=?""",
                (meta["binding"],)).fetchone()
        if not row or not all(row):
            return None
        provider = meta["provider"].upper()
        account, project = row
        account_tag = hashlib.sha256((provider + "\\0" + account).encode()).hexdigest()[:16]
        project_tag = hashlib.sha256(
            (provider + "\\0" + account + "\\0" + project).encode()
        ).hexdigest()[:16]
        return ("account:" + account_tag, "project:" + project_tag)

    def require(self, meta, payload):
        decision = self.decide(meta)
        if not decision.allowed:
            raise PermissionError("FREE_ROUTE_DENIED:" + decision.reason)
        if not isinstance(payload, dict):
            raise PermissionError("FREE_ROUTE_DENIED:INVALID_PAYLOAD")
        # Keep the existing fixed-adapter contract; this is not a
        # billing-monitoring or per-request pricing-verification loop.
        if "service_tier" in payload and payload["service_tier"] != "on_demand":
            raise PermissionError("FREE_ROUTE_DENIED:UNBOUND_SERVICE_TIER")
        if meta.get("protocol") not in ("exa-search", "tavily-search"):
            if payload.get("model") != meta["model"]:
                raise PermissionError("FREE_ROUTE_DENIED:MODEL_OVERRIDE")
        # Provider-hosted built-in tools are separately metered and cannot
        # inherit a FREE model's billing approval. Future preview/custom
        # tool types must fail closed, not bypass a short denylist.
        tools = payload.get("tools", ())
        if (tools is None):
            tools = ()
        if (type(tools) not in (list, tuple)
                or any(type(tool) is not dict or tool.get("type") != "function"
                       for tool in tools)):
            raise PermissionError("FREE_ROUTE_DENIED:UNPRICED_PROVIDER_TOOLS")
        if any(k in payload for k in ("models", "provider", "fallback_models", "plugins")):
            raise PermissionError("FREE_ROUTE_DENIED:UNBOUND_UPSTREAM")
        # Built-in paid features can also be enabled as TOP-LEVEL parameters,
        # even with no tools array. A FREE model selection is not authority
        # to activate provider-hosted search, audio, image, or preview billing.
        if any(k in payload for k in (
                "web_search_options", "audio", "modalities", "prediction",
                "image_generation", "file_search", "video",
                "response_modalities", "provider_options")):
            raise PermissionError("FREE_ROUTE_DENIED:UNPRICED_PROVIDER_FEATURE")
