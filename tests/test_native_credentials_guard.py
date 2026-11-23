from ai_foundation.credentials import CredentialGrant, InMemoryCredentialProvider, ProviderCredentialBoundary
from ai_foundation.core import CanonContract, GuardState, TaskPlan
from ai_foundation.guard import GuardCore
from ai_foundation.native_credentials import NativeCredentialProvider

class AvailabilityBoundary:
    def __init__(self, metadata_boundary, native_provider):
        self.metadata_boundary=metadata_boundary; self.native_provider=native_provider
    def authorize(self,binding,target):
        return self.metadata_boundary.authorize(binding,target) and self.native_provider.available(binding)

class Port:
    def __init__(self): self.n=0; self.value=''
    def execute(self,p): self.n+=1; self.value=p.text
    def observe(self,p): return self.value

def test_guard_denies_when_native_secret_is_unavailable(monkeypatch):
    class Missing:
        def available(self,b): return False
    meta=ProviderCredentialBoundary(InMemoryCredentialProvider([CredentialGrant('g','repo')]))
    boundary=AvailabilityBoundary(meta,Missing()); port=Port()
    plan=TaskPlan('r','write','repo',text='ok',canon_revision='c',credential_binding='g')
    assert GuardCore(GuardState(),credential_boundary=boundary).execute(plan,CanonContract('x','c'),port,'ok')=='DENY'
    assert port.n==0

def test_guard_allows_only_when_metadata_and_native_secret_are_current():
    class Present:
        def available(self,b): return b=='g'
    meta=ProviderCredentialBoundary(InMemoryCredentialProvider([CredentialGrant('g','repo')]))
    boundary=AvailabilityBoundary(meta,Present()); port=Port()
    plan=TaskPlan('r','write','repo',text='ok',canon_revision='c',credential_binding='g')
    assert GuardCore(GuardState(),credential_boundary=boundary).execute(plan,CanonContract('x','c'),port,'ok')=='VERIFIED_COMPLETE'
    assert port.n==1
