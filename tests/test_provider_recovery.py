from ai_foundation.provider_recovery import ProviderRecoveryLoop
class S:
 def __init__(self):self.rows=[{'binding':'rate','health':'RATE_LIMITED'},{'binding':'down','health':'DOWN'},{'binding':'ok','health':'ONLINE'}];self.seen=[]
 def credentials(self):return tuple(self.rows)
 def refresh_provider(self,b):self.seen.append(b);return {'provider':b,'health':'ONLINE'}
def test_recovery_rechecks_only_excluded_capacity():
 s=S();r=ProviderRecoveryLoop(s);out=r.tick();assert s.seen==['rate','down'];assert len(out)==2
class R:
 def credentials(self):return ({'binding':'bad','health':'RATE_LIMITED'},{'binding':'next','health':'DOWN'})
 def refresh_provider(self,b):
  if b=='bad':raise RuntimeError('still down')
  return {'provider':b,'health':'ONLINE'}
def test_recovery_failure_does_not_block_other_provider():assert ProviderRecoveryLoop(R()).tick()==({'provider':'next','health':'ONLINE'},)

def test_overlapping_ticks_do_not_multiply_provider_probes():
 import threading,time
 class Slow:
  def __init__(self):self.calls=0;self.enter=threading.Event();self.release=threading.Event()
  def credentials(self):return ({'binding':'b','health':'DOWN'},)
  def refresh_provider(self,b):self.calls+=1;self.enter.set();self.release.wait(2);return {'provider':'b','health':'DOWN'}
 s=Slow();loop=ProviderRecoveryLoop(s);out=[];t=threading.Thread(target=lambda:out.append(loop.tick()));t.start();assert s.enter.wait(1)
 assert loop.tick()==() and s.calls==1
 s.release.set();t.join();assert s.calls==1


def test_rate_limited_provider_is_not_reprobed_every_tick(monkeypatch):
 import ai_foundation.provider_recovery as m
 now=[1000.0];monkeypatch.setattr(m.time,'time',lambda:now[0])
 class X(S):
  def __init__(self):self.rows=[{'binding':'rate','health':'RATE_LIMITED'}];self.seen=[]
  def refresh_provider(self,b):self.seen.append(b);return {'provider':b,'health':'RATE_LIMITED'}
 x=X();loop=ProviderRecoveryLoop(x);loop.tick();now[0]+=60;loop.tick();assert x.seen==['rate']

def test_rate_limit_reset_evidence_controls_reprobe(monkeypatch):
 import ai_foundation.provider_recovery as m
 now=[1000.0];monkeypatch.setattr(m.time,'time',lambda:now[0])
 class Routing:
  _seconds=staticmethod(lambda x:120 if x=='120s' else None)
 class X(S):
  routing=Routing()
  def __init__(self):self.rows=[{'binding':'rate','health':'RATE_LIMITED','short_reset':'120s'}];self.seen=[]
  def refresh_provider(self,b):self.seen.append(b);return {'provider':b,'health':'RATE_LIMITED'}
 x=X();loop=ProviderRecoveryLoop(x);loop.tick();now[0]+=119;loop.tick();now[0]+=1;loop.tick();assert x.seen==['rate','rate']


def test_recovery_loop_survives_transient_credentials_db_failure():
 import threading
 recovered=threading.Event()
 class S:
  def __init__(self): self.calls=0
  def credentials(self):
   self.calls+=1
   if self.calls==1: raise __import__('sqlite3').OperationalError('unable to open database file')
   recovered.set()
   return ()
 s=S();loop=ProviderRecoveryLoop(s,interval=0.01);t=loop.start()
 try:
  assert recovered.wait(5), 'recovery never retried after the transient storage failure'
  assert t.is_alive() and s.calls>1
 finally:
  loop.stop();t.join(1)
 assert not t.is_alive()
