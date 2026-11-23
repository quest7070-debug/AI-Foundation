from ai_foundation.credentials import *
def test_exact_binding_target_principal_tenant_role():
 g=CredentialGrant('github','repo','alice','t1','writer')
 b=ProviderCredentialBoundary(InMemoryCredentialProvider([g]),'alice','t1',('writer',))
 assert b.authorize('github','repo')
 assert not b.authorize('github','other')
 assert not ProviderCredentialBoundary(InMemoryCredentialProvider([g]),'bob','t1',('writer',)).authorize('github','repo')
 assert not ProviderCredentialBoundary(InMemoryCredentialProvider([g]),'alice','t2',('writer',)).authorize('github','repo')
 assert not ProviderCredentialBoundary(InMemoryCredentialProvider([g]),'alice','t1',('reader',)).authorize('github','repo')
def test_revoke_is_seen_on_next_authorization():
 p=InMemoryCredentialProvider([CredentialGrant('x','target')]); b=ProviderCredentialBoundary(p)
 assert b.authorize('x','target'); p.revoke('x'); assert not b.authorize('x','target')
