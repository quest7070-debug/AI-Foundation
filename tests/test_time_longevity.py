import os,sqlite3,time
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.durable_inference import SQLiteInferenceAttemptStore
from ai_foundation.retention import RetentionService,RetentionPolicy
from ai_foundation.local_health import LocalFailureCooldown
from ai_foundation.long_term_health import LongTermHealthLoop,LongTermHealth,LongTermSignal
from ai_foundation.remote_access import RemoteAccess,RemoteAccessConfig
from ai_foundation.startup import StartupRecovery

def stores(tmp_path):
 g=tmp_path/'g.db';w=tmp_path/'w.db';i=tmp_path/'i.db';SQLiteGuardStore(g);SQLiteWorkStore(w);SQLiteInferenceAttemptStore(i);return g,w,i

def test_calendar_boundaries_are_epoch_authority_and_timezone_presentation_only(monkeypatch):
 instants=[datetime(2024,2,29,23,59,59,tzinfo=timezone.utc),datetime(2024,12,31,23,59,59,tzinfo=timezone.utc),datetime(2026,11,1,5,30,tzinfo=timezone.utc),datetime(2026,11,1,6,30,tzinfo=timezone.utc)]
 epochs=[x.timestamp() for x in instants]
 assert epochs==sorted(epochs) and len(set(epochs))==len(epochs)
 # The two UTC instants deliberately render as the repeated 01:30 during New York DST fall-back,
 # yet remain distinct authority timestamps. Tokyo has no DST and is presentation-only too.
 ny=[x.astimezone(ZoneInfo('America/New_York')) for x in instants[-2:]]
 assert [x.strftime('%H:%M') for x in ny]==['01:30','01:30'] and ny[0].utcoffset()!=ny[1].utcoffset()
 assert instants[0].astimezone(ZoneInfo('Asia/Tokyo')).timestamp()==epochs[0]

def test_backward_wall_clock_step_fails_closed_for_destructive_retention(tmp_path):
 g,w,i=stores(tmp_path); now=[2_000_000_000.]
 with sqlite3.connect(i) as d:d.execute("INSERT INTO inference_attempts VALUES('v','b','VERIFIED','x',?)",(now[0]-100*86400,))
 svc=RetentionService(g,w,i,clock=lambda:now[0]); now[0]-=3600
 assert svc.prune()=={'effect_claims':0,'target_claims':0,'startup_leases':0,'human_inputs':0,'inference_attempts':0}
 with sqlite3.connect(i) as d:assert d.execute("SELECT COUNT(*) FROM inference_attempts WHERE request_id='v'").fetchone()[0]==1
 now[0]+=7200;assert svc.prune()['inference_attempts']==1

def test_backward_and_forward_wall_steps_do_not_resurrect_claims_or_fresh_health(tmp_path):
 g,_,_=stores(tmp_path);s=SQLiteGuardStore(g)
 assert s.try_claim('e','a',100,ttl=30);assert not s.try_claim('e','b',90,ttl=30);assert s.try_claim('e','b',131,ttl=30)
 now=[100.];loop=LongTermHealthLoop(lambda:LongTermHealth(now[0],(LongTermSignal('x',True,'ok'),)),interval=60,clock=lambda:now[0])
 loop.tick();now[0]=90;assert loop.trustworthy() is None
 now[0]=221;assert loop.trustworthy() is None

def test_local_failure_requires_observed_success_to_recover():
 now=[10.];h=LocalFailureCooldown(ttl=30,clock=lambda:now[0]);h.fail('m');assert h.excluded()=={'m'}
 # Elapsed time is not positive health evidence. Only a real successful execution clears failure.
 now[0]=10_000.;assert h.excluded()=={'m'}
 h.success('m');assert not h.excluded()

def test_remote_session_forward_and_backward_wall_steps_fail_closed():
 a=RemoteAccess(RemoteAccessConfig('x'*32,frozenset({'example.test'})));s=a.issue_session(now=1000)
 assert a.session_valid(s,now=1001);assert not a.session_valid(s,now=900);assert not a.session_valid(s,now=1000+31*86400)

def test_long_offline_startup_releases_only_stale_or_terminal_budget(tmp_path):
 g,_,_=stores(tmp_path);s=SQLiteGuardStore(g);now=2_000_000_000.
 with sqlite3.connect(g) as d:
  d.executemany('INSERT INTO budget_reservations VALUES(?,?,?)',[('ancient-orphan',1,now-3*365*86400),('recent-orphan',1,now-10),('terminal',1,now-3*365*86400)])
  d.execute("INSERT INTO effects VALUES('e','terminal','t','x','VERIFIED',0,?)",(now-3*365*86400,))
 report=StartupRecovery(s,min_age=60,clock=lambda:now).run();assert report.acquired and report.released_budget_reservation_count==2
 with sqlite3.connect(g) as d:assert d.execute('SELECT run_id FROM budget_reservations').fetchall()==[('recent-orphan',)]

def test_accelerated_retention_month_year_three_year_boundaries(tmp_path):
 g,w,i=stores(tmp_path);base=1_700_000_000.;now=[base]
 with sqlite3.connect(w) as d:
  for name,age in [('m',31),('y',366),('3y',3*366)]:d.execute('INSERT INTO human_inputs VALUES(?,?,?,?,?,NULL)',(name,0,'x',base-age*86400,base-age*86400))
 with sqlite3.connect(i) as d:
  for name,age in [('m',31),('y',366),('3y',3*366)]:d.execute('INSERT INTO inference_attempts VALUES(?,?,?,?,?)',(name,'b','VERIFIED','x',base-age*86400))
 svc=RetentionService(g,w,i,RetentionPolicy(),lambda:now[0])
 first=svc.prune();assert first['human_inputs']==3 and first['inference_attempts']==2 # 90d terminal policy keeps 31d inference
 now[0]+=3*365*86400;second=svc.prune();assert second['inference_attempts']==1
 assert svc.prune()['inference_attempts']==0
