#!/usr/bin/env python3
"""Bounded production SEARCH provider sweep: real success, reversible primary outage, failover, recovery, trace."""
import json,time,uuid
from pathlib import Path
from ai_foundation.productization import load_config
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.guard import GuardCore
from ai_foundation.core import TaskPlan,CanonContract
from ai_foundation.inference_composition import build_inference_composition
from ai_foundation.http_transport import UrllibCloudTransport
from ai_foundation.observability import JsonlTraceSink,Tracer,read_jsonl_trace

class PrimaryOutageTransport:
 def __init__(self,inner,provider):self.inner=inner;self.provider=provider.upper();self.blocked=0
 def send(self,provider,secret,payload):
  if provider.upper()==self.provider:
   # A definitive HTTP 503 is the safe failover proof. A transport exception is intentionally
   # ambiguous and must stop at UNCERTAIN_RECONCILE_REQUIRED rather than blind-fail over.
   from ai_foundation.cloud_execution import CloudResponse
   self.blocked+=1;return CloudResponse(503,{},'controlled primary outage')
  return self.inner.send(provider,secret,payload)

def main(config_path):
 c=load_config(config_path);root=Path(c.data_dir);trace=root/c.trace_file
 guard=GuardCore(SQLiteGuardStore(root/c.guard_db).runtime_state())
 baseline=build_inference_composition(root=root,config=c,guard=guard,optimize=False,tracer=Tracer(JsonlTraceSink(trace)))
 route=baseline.settings.route('SEARCH');ordered=((route.primary,) if route.primary else ())+route.standby
 if len(ordered)<2:raise SystemExit('SEARCH needs at least two configured candidates')
 primary=baseline.settings.registry.credential(ordered[0]);standby=baseline.settings.registry.credential(ordered[1])
 if not primary or not standby or primary['health']!='ONLINE' or standby['health']!='ONLINE':raise SystemExit('SEARCH primary/standby must begin ONLINE')
 before=len(read_jsonl_trace(trace)) if trace.exists() else 0
 def run(service,label):
  rid='search-sweep-'+label+'-'+uuid.uuid4().hex[:8]
  p=TaskPlan(rid,'compute','llm',text='Explain DNS in one sentence.',canon_revision='search-sweep',effect_id=rid+':inference',privacy_text='Explain DNS in one sentence.')
  return rid,service.run(p,CanonContract('search-sweep','search-sweep'),function='SEARCH')
 normal_id,normal=run(baseline.service,'normal')
 if normal.status!='VERIFIED_COMPLETE':raise SystemExit('baseline SEARCH failed')
 injected=PrimaryOutageTransport(UrllibCloudTransport(),primary['provider'])
 fail=build_inference_composition(root=root,config=c,guard=guard,transport=injected,optimize=False,tracer=Tracer(JsonlTraceSink(trace)))
 try:
  fail_id,failed=run(fail.service,'failover')
  if failed.status!='VERIFIED_COMPLETE' or failed.route_binding==primary['binding'] or injected.blocked<1:raise SystemExit('controlled failover failed')
  down=fail.settings.registry.credential(primary['binding'])
  if down['health']!='DOWN':raise SystemExit('primary outage not observed')
 finally:
  recovered=baseline.settings.refresh_provider(primary['binding'])
 if recovered['health']!='ONLINE':raise SystemExit('primary recovery probe failed')
 baseline.settings.optimize_routing('SEARCH')
 recovered_id,recovered_run=run(baseline.service,'recovered')
 if recovered_run.status!='VERIFIED_COMPLETE' or recovered_run.route_binding!=primary['binding']:raise SystemExit('primary did not regain route')
 events=read_jsonl_trace(trace)[before:]
 attempts=[e for e in events if e.name=='inference.attempt' and e.attributes.get('run_id') in {normal_id,fail_id,recovered_id}]
 byrun={r:[e.attributes.get('route_binding') for e in attempts if e.attributes.get('run_id')==r] for r in (normal_id,fail_id,recovered_id)}
 if byrun[normal_id]!=[normal.route_binding] or byrun[fail_id][:2]!=[primary['binding'],failed.route_binding] or byrun[recovered_id]!=[primary['binding']]:raise SystemExit('trace route sequence mismatch')
 print(json.dumps({'status':'PASS','search_order_providers':[primary['provider'],standby['provider']],'baseline_provider':primary['provider'],'failover_provider':fail.settings.registry.credential(failed.route_binding)['provider'],'primary_observed_down':True,'primary_definitive_503s':injected.blocked,'recovery':'ONLINE','trace_attempts':{normal_id:len(byrun[normal_id]),fail_id:len(byrun[fail_id]),recovered_id:len(byrun[recovered_id])}},separators=(',',':')))
if __name__=='__main__':
 import sys;main(sys.argv[1])
