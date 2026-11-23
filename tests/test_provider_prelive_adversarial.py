import threading
import pytest
from ai_foundation.provider_registry import SQLiteProviderRegistry
from ai_foundation.provider_onboarding import ProviderOnboarding,ProbeResult
from ai_foundation.cloud_execution import ObservedCloudExecution,CloudResponse
from ai_foundation.provider_observer import ProviderResponseObserver

class Store:
 def __init__(self): self.d={}
 def save(self,b,s): self.d[b]=s
 def load(self,b): return self.d[b]
 def delete(self,b): return self.d.pop(b,None) is not None
class Probe:
 def probe(self,s,h=None): return ProbeResult(h or 'GROQ','ONLINE',80,'1m',70,'1d')
class Tx:
 def send(self,p,s,payload): return CloudResponse(200,{},'ok')

def test_secret_never_enters_sqlite_file(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite'); s=Store(); secret='gsk_'+'ULTRASECRET'*4
 ProviderOnboarding(r,s,Probe()).add(secret)
 assert secret.encode() not in (tmp_path/'p.sqlite').read_bytes()

def test_concurrent_registry_observation_keeps_database_valid(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite'); r.upsert('b','GROQ',short_remaining=90,long_remaining=90)
 errors=[]
 def worker(i):
  try:
   for _ in range(20): r.observe('b',health='ONLINE',short_remaining=i,active=bool(i%2))
  except Exception as e: errors.append(e)
 ts=[threading.Thread(target=worker,args=(i,)) for i in range(8)]
 [t.start() for t in ts]; [t.join() for t in ts]
 assert not errors and r.credential('b')['health']=='ONLINE'

def test_unknown_binding_cannot_execute(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite')
 with pytest.raises(KeyError): ObservedCloudExecution(r,Store(),ProviderResponseObserver(r),Tx()).invoke('missing',{})

def test_transport_body_cannot_overwrite_registry_identity(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite'); r.upsert('b','GROQ',short_remaining=90,long_remaining=90); s=Store(); s.d['b']='secret'
 class Evil:
  def send(self,*a): return CloudResponse(200,{},'{"provider":"EVIL","binding":"other"}')
 ObservedCloudExecution(r,s,ProviderResponseObserver(r),Evil()).invoke('b',{})
 c=r.credential('b'); assert c['provider']=='GROQ' and c['binding']=='b'
