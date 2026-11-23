"""Reviewed, explicit Harness proposal-adapter registry.

A new provider must provide a pinned model/endpoint, a reviewed proposal-only
transport, and an manually selected no-charge FREE account. Discovery and account
registration are never capability grants. No dynamic import by service name,
network discovery, paid fallback, or model-chosen provider registration.
"""
from dataclasses import dataclass
from typing import Callable

from .free_route_admission import fixed_model
from .next_service_preflight import reviewable_free_model
from .provider_catalog import spec


@dataclass(frozen=True)
class HarnessServiceAdapter:
    provider: str
    model: str
    endpoint: str
    transport_factory: Callable
    capabilities: tuple[str, ...] = ("CODE",)


class HarnessServiceRegistry:
    """Host-supplied, source-reviewed services rather than Harness conditionals."""

    def __init__(self, adapters=()):
        by_provider = {}
        for adapter in adapters:
            if not isinstance(adapter, HarnessServiceAdapter):
                raise TypeError("HARNESS_SERVICE_ADAPTER_REQUIRED")
            catalog = spec(adapter.provider)
            if (not catalog or adapter.provider != catalog.name
                    or adapter.provider in by_provider
                    or not (adapter.model == catalog.model or
                            (adapter.provider == "OPENCODE" and
                             reviewable_free_model(adapter.model)))
                    or adapter.endpoint != catalog.endpoint
                    or not fixed_model(adapter.model)
                    or catalog.protocol not in ("openai-chat", "gemini-generate", "cohere-v2", "opencode-cli")
                    or not callable(adapter.transport_factory)
                    or not adapter.capabilities
                    or any(c not in catalog.capabilities for c in adapter.capabilities)
                    or "CODE" not in adapter.capabilities):
                raise ValueError("HARNESS_UNPINNED_OR_UNSUPPORTED_ADAPTER")
            by_provider[adapter.provider] = adapter
        self._adapters = by_provider

    def providers(self):
        return tuple(sorted(self._adapters))

    def get(self, provider):
        return self._adapters.get(provider)

    def admitted(self, meta, free_route, *, capability="CODE"):
        if type(meta) is not dict or free_route is None:
            return False
        adapter = self.get(meta.get("provider"))
        if (adapter is None or capability not in adapter.capabilities
                or meta.get("tier") != "FREE"
                or meta.get("model") != adapter.model
                or meta.get("endpoint") != adapter.endpoint
                # First-time UNVERIFIED health may proceed only when the
                # manual Free-service choice below is valid.
                or meta.get("health") not in ("ONLINE", "UNVERIFIED")):
            return False
        # Manual selection is bound to the exact credential + provider + model
        # + endpoint and to the owner's chosen account/project scope.
        return free_route.decide(meta).allowed

    def transport(self, meta, free_route):
        if not self.admitted(meta, free_route):
            raise PermissionError("HARNESS_SERVICE_NOT_ADMITTED")
        factory = self.get(meta["provider"]).transport_factory
        # CLI agents require their exact manually selected credential binding.
        # Unlike HTTP transports this factory receives no API secret or URL.
        if meta["provider"] == "OPENCODE":
            return factory(meta["binding"])
        return factory()
