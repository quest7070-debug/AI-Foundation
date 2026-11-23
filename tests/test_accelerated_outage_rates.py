"""Accelerated outage evidence for bounded periodic work (LT51)."""
from ai_foundation.provider_recovery import ProviderRecoveryLoop
from ai_foundation.push_dispatch import PushDispatch

class DownSettings:
 def __init__(self):self.calls=0
 def credentials(self):return ({'binding':'down','health':'DOWN'},)
 def refresh_provider(self,b):self.calls+=1;raise RuntimeError('still down')

class FailedPush:
 def __init__(self):self.calls=0
 def deliver(self,p):self.calls+=1;raise RuntimeError('offline')

def notice():return {'notices':[{'level':4,'kind':'work','subject':'same-outage','status':'FAILED','summary_ja':'x'}]}

def test_accelerated_hour_provider_recovery_respects_real_time_backoff(monkeypatch):
 s=DownSettings();now=[0.0];monkeypatch.setattr('ai_foundation.provider_recovery.time.time',lambda:now[0]);loop=ProviderRecoveryLoop(s,interval=60)
 for _ in range(60):
  assert loop.tick()==();now[0]+=60
 assert s.calls==60

def test_accelerated_hour_failed_push_has_one_attempt_per_poll_not_amplification(tmp_path):
 t=FailedPush();d=PushDispatch(t,tmp_path/'seen.json')
 # 720 accelerated polls represent one hour at the production 5-second floor.
 for _ in range(720):
  r=d.dispatch(notice());assert r=={'sent_notices':0,'failed_notices':1}
 assert t.calls==720


def test_accelerated_day_failed_push_has_bounded_state_and_no_log_amplification(tmp_path):
 t=FailedPush();state=tmp_path/'seen.json';d=PushDispatch(t,state)
 # 17,280 polls = 24h at the production 5s floor. A failed transport retries once per poll,
 # never writes dedupe state and PushDispatch itself emits no per-attempt log side effect.
 for _ in range(17280):
  r=d.dispatch(notice());assert r=={'sent_notices':0,'failed_notices':1}
 assert t.calls==17280 and not state.exists()

def test_accelerated_day_provider_outage_respects_real_time_backoff(monkeypatch):
 s=DownSettings();now=[0.0];monkeypatch.setattr('ai_foundation.provider_recovery.time.time',lambda:now[0]);loop=ProviderRecoveryLoop(s,interval=60)
 for _ in range(1440):
  assert loop.tick()==();now[0]+=60
 assert s.calls==1440
