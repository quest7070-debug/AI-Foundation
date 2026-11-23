from ai_foundation.push_credentials import VapidCredential,VapidCredentialStore,BINDING
class Store:
 def __init__(self):self.d={}
 def save(self,k,v):self.d[k]=v
 def load(self,k):return self.d[k]
 def available(self,k):return k in self.d
def test_vapid_uses_native_secret_boundary_and_roundtrips():
 s=Store();v=VapidCredentialStore(s);c=VapidCredential('PRIVATE','PUBLIC','mailto:x@example.invalid');v.save(c)
 assert v.available() and v.load()==c and BINDING in s.d and 'PRIVATE' in s.d[BINDING]
def test_vapid_secret_repr_is_not_credential_value():
 c=VapidCredential('PRIVATE','PUBLIC','mailto:x@example.invalid')
 assert 'PRIVATE' not in repr(c) and 'PUBLIC' not in repr(c) and 'example.invalid' not in repr(c)
