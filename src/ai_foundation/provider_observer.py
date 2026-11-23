from dataclasses import dataclass
from .provider_quota import groq_quota,mistral_short_quota
from .provider_catalog import spec

@dataclass(frozen=True)
class Observation:
    health:str; reason:str|None; quota_seen:bool

class ProviderResponseObserver:
    def __init__(self,registry): self.registry=registry
    def observe(self,binding,provider,status,headers):
        provider=provider.upper(); status=int(status); health='ONLINE'; reason=None
        if status in (401,403): health='CREDENTIAL_ERROR'; reason=f'HTTP {status}'
        elif status==429: health='RATE_LIMITED'; reason='HTTP 429'
        elif status>=500: health='DOWN'; reason=f'HTTP {status}'
        quota=None
        quota_style=(spec(provider).quota_style if spec(provider) else None)
        if quota_style=='groq': quota=groq_quota(headers)
        elif quota_style=='mistral':
            short=mistral_short_quota(headers)
            if short: quota=(short,None)
        kw={'health':health,'active':True,'reason':reason}
        if quota:
            short,long=quota
            kw.update(short_remaining=short.remaining,short_reset=short.reset)
            if long: kw.update(long_remaining=long.remaining,long_reset=long.reset)
        if not self.registry.observe(binding,**kw): raise KeyError(binding)
        return Observation(health,reason,bool(quota))
    def finish(self,binding):
        if not self.registry.observe(binding,active=False): raise KeyError(binding)
