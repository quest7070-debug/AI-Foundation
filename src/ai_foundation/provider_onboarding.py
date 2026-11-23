from dataclasses import dataclass
import secrets
from typing import Protocol
from .provider_catalog import detect as detect_provider, spec as provider_spec

@dataclass(frozen=True)
class ProbeResult:
    provider:str|None; health:str; short_remaining:float|None=None; short_reset:str|None=None
    long_remaining:float|None=None; long_reset:str|None=None; reason:str|None=None

class ProviderProbe(Protocol):
    def probe(self,secret:str,provider_hint:str|None=None)->ProbeResult: ...

class ProviderOnboarding:
    def __init__(self,registry,secret_store,probe,duplicate_checker=None): self.registry=registry; self.secret_store=secret_store; self.probe=probe; self.duplicate_checker=duplicate_checker
    def add(self,secret,provider_hint=None,tier='FREE'):
        if not secret or not secret.strip(): raise ValueError('API key required')
        secret=secret.strip(); detected=detect_provider(secret); hint=provider_hint.upper() if provider_hint else None
        if self.duplicate_checker and self.duplicate_checker(secret): raise ValueError('credential already registered')
        # Explicit selection is authoritative when AUTO cannot recognize a key family.
        # Known key prefixes still override a conflicting hint to prevent cross-provider leakage.
        selected=detected or hint
        result=self.probe.probe(secret,selected)
        provider=(result.provider or selected)
        if not provider: raise ValueError('provider selection required')
        if result.health not in {'ONLINE','RATE_LIMITED'}: raise ValueError(result.reason or 'provider validation failed')
        # A valid FREE credential is registrable even when the provider does not expose
        # machine-readable remaining quota. Unknown quota stays unknown; it is never fabricated.
        binding=f"llm:{provider.lower()}:{secrets.token_hex(6)}"
        self.secret_store.save(binding,secret)
        try:
            ps=provider_spec(provider)
            self.registry.upsert(binding,provider,tier,result.health,result.short_remaining,result.short_reset,result.long_remaining,result.long_reset,endpoint=(ps.endpoint if ps else None),model=(ps.model if ps else None),auth_style=(ps.auth_style if ps else None),protocol=(ps.protocol if ps else None),capabilities=(ps.capabilities if ps else ()))
        except Exception:
            self.secret_store.delete(binding)
            raise
        return binding
