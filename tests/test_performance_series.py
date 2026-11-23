"""Comparable deterministic performance series for LT58 regression tracking."""
import statistics,time
from ai_foundation.settings_service import SettingsService
from ai_foundation.provider_onboarding import ProbeResult
from ai_foundation.compute_routing import ComputeRouter
from ai_foundation.local_compute_registry import LocalComputeRegistry,LocalComputeCandidate
class Secrets:
 def save(self,*a):pass
 def load(self,*a):return 'x'
 def delete(self,*a):return True
 def available(self,*a):return True
class Probe:
 def probe(self,s,h=None):return ProbeResult(h or 'GROQ','ONLINE',80,'1m',70,'1d')

def _series(fn,n=100):
 xs=[]
 for _ in range(n):
  t=time.perf_counter();fn();xs.append((time.perf_counter()-t)*1000)
 ordered=sorted(xs)
 p95=ordered[int((len(ordered)-1)*0.95)]
 return statistics.median(xs),p95

def test_provider_selection_latency_series_has_broad_regression_ceiling(tmp_path):
 svc=SettingsService(tmp_path/'settings',Probe(),Secrets(),local_compute=LocalComputeRegistry(lambda:(LocalComputeCandidate('local:x',health='ONLINE',capabilities=('CHAT','SEARCH'),model='x'),)))
 svc.optimize_all_routes();router=ComputeRouter(svc,svc.local_compute)
 median,p95=_series(lambda:router.choose('CHAT'),200)
 # Broad percentile ceilings detect sustained scans/I/O explosions while excluding
 # isolated host-scheduler stalls from this deterministic regression contract.
 assert median<20 and p95<100

def test_settings_startup_latency_series_has_broad_regression_ceiling(tmp_path):
 root=tmp_path/'settings';SettingsService(root,Probe(),Secrets())
 median,p95=_series(lambda:SettingsService(root,Probe(),Secrets()),50)
 assert median<50 and p95<250
