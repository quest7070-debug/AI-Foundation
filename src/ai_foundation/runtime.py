from dataclasses import dataclass
import time
from typing import Callable, Protocol


class DurableRuntime(Protocol):
    def health(self) -> dict: ...


@dataclass
class GuardedRuntimeCall:
    """Keep runtime redelivery from turning a live Guard lease into an app failure."""
    retry_interval: float = 0.25
    wait_timeout: float = 35.0

    def run(self, call: Callable[[], str]) -> str:
        deadline = time.monotonic() + self.wait_timeout
        while True:
            result = call()
            if result not in {"EFFECT_IN_PROGRESS", "TARGET_IN_PROGRESS"}:
                return result
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return result
            time.sleep(min(self.retry_interval, remaining))


@dataclass
class HatchetRuntime:
    """Hatchet adapter boundary. Guard remains outside the runtime."""
    embedded: bool = True
    client_factory: object|None = None
    external_configured: bool = False

    def _external_client(self):
        if self.client_factory is not None: return self.client_factory()
        from hatchet_sdk import Hatchet
        return Hatchet()

    def health(self) -> dict:
        try:
            from hatchet_sdk import Hatchet
            if not self.embedded:
                if self.client_factory is None and not self.external_configured:
                    return {"ok": False, "mode": "external", "reason": "not_configured"}
                try:
                    client=self._external_client()
                    version=client.get_engine_version()
                    return {"ok": True, "mode": "external", "version": str(version)}
                except Exception as exc:
                    return {"ok": False, "mode": "external", "reason": type(exc).__name__}
            client = Hatchet.from_embedded()
            try:
                version = client.get_engine_version()
                return {"ok": True, "mode": "embedded", "version": str(version)}
            finally:
                client.stop_embedded()
        except Exception as exc:
            # Health is operator-visible durable-ish state; SDK errors may embed endpoints/tokens.
            return {"ok": False, "mode": "embedded", "reason": type(exc).__name__}
