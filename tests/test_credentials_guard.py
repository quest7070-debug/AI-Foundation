from ai_foundation.credentials import *
from ai_foundation.core import *
from ai_foundation.guard import GuardCore
class P:
 def __init__(self): self.n=0; self.v=''
 def execute(self,p): self.n+=1; self.v=p.text
 def observe(self,p): return self.v
def test_provider_boundary_revoke_before_effect_denies():
 provider=InMemoryCredentialProvider([CredentialGrant('g','repo')])
 boundary=ProviderCredentialBoundary(provider); port=P()
 class RevokeOnSecond:
  def __init__(self): self.n=0
  def authorize(self,b,t):
   self.n+=1
   if self.n==2: provider.revoke(b)
   return boundary.authorize(b,t)
 plan=TaskPlan('r','write','repo',text='ok',canon_revision='c',credential_binding='g')
 assert GuardCore(GuardState(),credential_boundary=RevokeOnSecond()).execute(plan,CanonContract('x','c'),port,'ok')=='DENY'
 assert port.n==0
