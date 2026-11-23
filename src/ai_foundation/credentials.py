from dataclasses import dataclass
from typing import Protocol
@dataclass(frozen=True)
class CredentialGrant:
 binding:str; target:str; principal:str='local-owner'; tenant:str='local'; role:str='owner'; active:bool=True
class CredentialProvider(Protocol):
 def get(self,binding:str): ...
class InMemoryCredentialProvider:
 def __init__(self,grants=()): self._grants={g.binding:g for g in grants}
 def get(self,binding): return self._grants.get(binding)
 def revoke(self,binding):
  g=self._grants.get(binding)
  if g: self._grants[binding]=CredentialGrant(g.binding,g.target,g.principal,g.tenant,g.role,False)
class ProviderCredentialBoundary:
 def __init__(self,provider,principal='local-owner',tenant='local',roles=('owner',)): self.provider=provider; self.principal=principal; self.tenant=tenant; self.roles=set(roles)
 def authorize(self,binding,target):
  g=self.provider.get(binding)
  return bool(g and g.active and g.target==target and g.principal==self.principal and g.tenant==self.tenant and g.role in self.roles)
