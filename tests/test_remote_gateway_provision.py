from scripts.provision_remote_gateway import provision,SESSION
class S:
 def __init__(self):self.d={}
 def available(self,k):return k in self.d
 def save(self,k,v):self.d[k]=v
def test_provision_is_idempotent_and_strong():
 s=S();assert provision(s)==(SESSION,);a=dict(s.d);assert provision(s)==();assert s.d==a
 assert len(s.d[SESSION])>=48
