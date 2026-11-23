from ai_foundation.routing import SQLiteRoutingPolicy
def c(b,t='FREE',h='ONLINE',s=80,l=80):return {'binding':b,'tier':t,'health':h,'short_remaining':s,'long_remaining':l}
def test_optimize_persists_primary_standby(tmp_path):
 r=SQLiteRoutingPolicy(tmp_path/'r.db');x=r.optimize('TEXT',[c('b',s=50),c('a',s=90),c('paid','PAID',s=100)]);assert x.primary=='a' and x.standby==('b','paid') and r.get('TEXT').primary=='a'
def test_health_skip_does_not_rewrite_order(tmp_path):
 r=SQLiteRoutingPolicy(tmp_path/'r.db');r.optimize('TEXT',[c('a'),c('b')]);assert r.choose('TEXT',[c('a',h='DOWN'),c('b')])=='b';assert r.get('TEXT').primary=='a'
def test_safety_margin_skips_near_empty(tmp_path):
 r=SQLiteRoutingPolicy(tmp_path/'r.db');r.optimize('TEXT',[c('a'),c('b')]);assert r.choose('TEXT',[c('a',s=3),c('b',s=20)])=='b'
def test_no_eligible_route_returns_none(tmp_path):
 r=SQLiteRoutingPolicy(tmp_path/'r.db');r.optimize('TEXT',[c('a',h='DOWN')]);assert r.choose('TEXT',[c('a',h='DOWN')]) is None

def test_fresh_routing_schema_has_no_retired_preferences(tmp_path):
 import sqlite3
 r=SQLiteRoutingPolicy(tmp_path/'fresh.db')
 with sqlite3.connect(tmp_path/'fresh.db') as db:
  cols={row[1] for row in db.execute('pragma table_info(routes)')}
 assert cols == {'function','ordered_bindings','optimized_at'}
 assert r.preferences('TEXT') == {}

def test_runtime_history_changes_execution_not_saved_display_order(tmp_path):
 r=SQLiteRoutingPolicy(tmp_path/'r.db');r.optimize('TEXT',[c('a'),c('b')])
 assert r.get('TEXT').primary=='a'
 r.record_runtime('TEXT','a',True,12000,now=100);r.record_runtime('TEXT','b',True,600,now=100)
 assert r.choose('TEXT',[c('a'),c('b')])=='b'
 assert r.get('TEXT').primary=='a' and r.get('TEXT').standby==('b',)

def test_failed_runtime_candidate_is_not_blindly_retried_first_next_request(tmp_path):
 r=SQLiteRoutingPolicy(tmp_path/'r.db');r.optimize('TEXT',[c('a'),c('b')])
 r.record_runtime('TEXT','a',False,30000,now=100);r.record_runtime('TEXT','b',True,1000,now=100)
 assert r.choose('TEXT',[c('a'),c('b')])=='b'

def test_elapsed_reset_text_does_not_invent_quota_recovery(tmp_path,monkeypatch):
 import ai_foundation.routing as mod
 monkeypatch.setattr(mod.time,'time',lambda:1000)
 r=SQLiteRoutingPolicy(tmp_path/'r.db');r.optimize('TEXT',[c('a'),c('b')])
 a=c('a',s=0.7);a.update(updated_at=900,short_reset='59.58s')
 assert r.choose('TEXT',[a,c('b')])=='b'

def test_fresh_low_quota_still_skips_candidate(tmp_path,monkeypatch):
 import ai_foundation.routing as mod
 monkeypatch.setattr(mod.time,'time',lambda:1000)
 r=SQLiteRoutingPolicy(tmp_path/'r.db');r.optimize('TEXT',[c('a'),c('b')])
 a=c('a',s=0.7);a.update(updated_at=980,short_reset='59.58s')
 assert r.choose('TEXT',[a,c('b')])=='b'


def test_runtime_history_is_capability_scoped(tmp_path):
 r=SQLiteRoutingPolicy(tmp_path/'r.db');r.optimize('CHAT',[c('shared'),c('chat2')]);r.optimize('SEARCH',[c('search1'),c('shared')])
 r.record_runtime('CHAT','shared',True,100,now=100)
 assert r.choose('SEARCH',[c('search1'),c('shared')])=='search1'


def test_runtime_history_does_not_manufacture_unobserved_standby_traffic(tmp_path):
 r=SQLiteRoutingPolicy(tmp_path/'r.db');r.optimize('CHAT',[c('a'),c('b')])
 r.record_runtime('CHAT','a',True,1000,now=100);r.record_runtime('CHAT','a',True,900,now=101);r.record_runtime('CHAT','a',True,800,now=102)
 assert r.choose('CHAT',[c('a'),c('b')])=='a'
 assert r.get('CHAT').primary=='a'

def test_runtime_history_does_not_probe_after_failed_winner(tmp_path):
 r=SQLiteRoutingPolicy(tmp_path/'r.db');r.optimize('CHAT',[c('a'),c('b')])
 for n in range(3):r.record_runtime('CHAT','a',True,1000,now=100+n)
 r.record_runtime('CHAT','a',False,2000,now=104)
 assert r.choose('CHAT',[c('a'),c('b')])=='a'


def test_stale_runtime_does_not_manufacture_reprobe_traffic(tmp_path,monkeypatch):
 import ai_foundation.routing as mod
 monkeypatch.setattr(mod.time,'time',lambda:5000)
 r=SQLiteRoutingPolicy(tmp_path/'r.db');r.optimize('CHAT',[c('a'),c('b')])
 r.record_runtime('CHAT','a',True,100,now=4900);r.record_runtime('CHAT','b',True,1000,now=100)
 assert r.choose('CHAT',[c('a'),c('b')])=='a'
 assert r.get('CHAT').primary=='a' and r.get('CHAT').standby==('b',)

def test_fresh_runtime_observations_use_measured_score(tmp_path,monkeypatch):
 import ai_foundation.routing as mod
 monkeypatch.setattr(mod.time,'time',lambda:5000)
 r=SQLiteRoutingPolicy(tmp_path/'r.db');r.optimize('CHAT',[c('a'),c('b')])
 r.record_runtime('CHAT','a',True,100,now=4900);r.record_runtime('CHAT','b',True,1000,now=4800)
 assert r.choose('CHAT',[c('a'),c('b')])=='a'


def test_recent_failure_temporarily_yields_to_healthy_alternative(tmp_path,monkeypatch):
 import ai_foundation.routing as m
 now=[1000.0];monkeypatch.setattr(m.time,'time',lambda:now[0])
 r=SQLiteRoutingPolicy(tmp_path/'r.db'); states=[{'binding':'a','health':'ONLINE'},{'binding':'b','health':'ONLINE'}]
 r.optimize('CHAT',states);r.record_runtime('CHAT','a',True,100,900);r.record_runtime('CHAT','b',True,200,900)
 assert r.choose('CHAT',states)=='a';r.record_runtime('CHAT','a',False,30000,1000);assert r.choose('CHAT',states)=='b'
 now[0]=1061;assert r.choose('CHAT',states) in {'a','b'}

def test_runtime_failure_is_capability_scoped(tmp_path,monkeypatch):
 import ai_foundation.routing as m
 monkeypatch.setattr(m.time,'time',lambda:1000.0)
 r=SQLiteRoutingPolicy(tmp_path/'r.db'); states=[{'binding':'a','health':'ONLINE'},{'binding':'b','health':'ONLINE'}]
 r.optimize('CHAT',states);r.optimize('SEARCH',states);r.record_runtime('CHAT','a',False,30000,1000);r.record_runtime('SEARCH','a',True,10,1000);r.record_runtime('SEARCH','b',True,20,1000)
 assert r.choose('SEARCH',states)=='a'


def test_failure_cooldown_backs_off_exponentially_and_success_resets_it(tmp_path,monkeypatch):
 import ai_foundation.routing as m,sqlite3
 now=[1000.0];monkeypatch.setattr(m.time,'time',lambda:now[0])
 r=SQLiteRoutingPolicy(tmp_path/'r.db');states=[c('a'),c('b')];r.optimize('CHAT',states)
 r.record_runtime('CHAT','a',True,100,900);r.record_runtime('CHAT','b',True,200,900)
 r.record_runtime('CHAT','a',False,30000,1000);now[0]=1061
 # first failure cools for 60s, then may be retried
 assert r.choose('CHAT',states) in {'a','b'}
 r.record_runtime('CHAT','a',False,30000,1061);now[0]=1120
 assert r.choose('CHAT',states)=='b'
 now[0]=1182;r.record_runtime('CHAT','a',True,100,1182)
 with sqlite3.connect(tmp_path/'r.db') as db: assert db.execute("select consecutive_failures from route_runtime where function='CHAT' and binding='a'").fetchone()[0]==0

def test_runtime_schema_migrates_failure_streak(tmp_path):
 import sqlite3
 r=SQLiteRoutingPolicy(tmp_path/'r.db')
 with sqlite3.connect(tmp_path/'r.db') as db: assert 'consecutive_failures' in {x[1] for x in db.execute('pragma table_info(route_runtime)')}


def test_measured_latency_beats_better_lifetime_failure_rate_without_provider_identity(tmp_path,monkeypatch):
 import ai_foundation.routing as m
 monkeypatch.setattr(m.time,'time',lambda:1000.0)
 r=SQLiteRoutingPolicy(tmp_path/'r.db');states=[c('slow'),c('fast')];r.optimize('CHAT',states)
 # slow has the better historical success ratio, but its successful completions are
 # far slower. Runtime selection must use generic observed service quality.
 for n in range(10): r.record_runtime('CHAT','slow',True,28000,900+n)
 r.record_runtime('CHAT','fast',True,700,900);r.record_runtime('CHAT','fast',False,700,901);r.record_runtime('CHAT','fast',True,700,902)
 assert r.choose('CHAT',states)=='fast'
 assert r.get('CHAT').primary=='fast' or r.get('CHAT').primary=='slow'

def test_recent_failure_still_outranks_latency(tmp_path,monkeypatch):
 import ai_foundation.routing as m
 monkeypatch.setattr(m.time,'time',lambda:1000.0)
 r=SQLiteRoutingPolicy(tmp_path/'r.db');states=[c('fast'),c('steady')];r.optimize('CHAT',states)
 r.record_runtime('CHAT','fast',True,100,900);r.record_runtime('CHAT','steady',True,1000,900)
 r.record_runtime('CHAT','fast',False,100,990)
 assert r.choose('CHAT',states)=='steady'

def test_failure_latency_never_becomes_success_quality(tmp_path,monkeypatch):
 import ai_foundation.routing as m
 monkeypatch.setattr(m.time,'time',lambda:2000.0)
 r=SQLiteRoutingPolicy(tmp_path/'r.db');states=[c('fails-fast'),c('works')];r.optimize('CHAT',states)
 for n in range(5): r.record_runtime('CHAT','fails-fast',False,5,100+n)
 r.record_runtime('CHAT','works',True,800,150)
 # Let failure cooldown expire. A fast failure is still not successful completion evidence.
 assert r.choose('CHAT',states)=='works'
 assert r.runtime('fails-fast')['success_latency_ms'] is None
 assert r.runtime('works')['success_latency_ms']==800

def test_failure_does_not_pollute_existing_success_latency(tmp_path):
 r=SQLiteRoutingPolicy(tmp_path/'r.db')
 r.record_runtime('CHAT','a',True,1000,100)
 r.record_runtime('CHAT','a',False,5,101)
 assert r.runtime('a')['success_latency_ms']==1000

def test_success_latency_ewma_uses_only_successes(tmp_path):
 r=SQLiteRoutingPolicy(tmp_path/'r.db')
 r.record_runtime('CHAT','a',True,1000,100)
 r.record_runtime('CHAT','a',False,1,101)
 r.record_runtime('CHAT','a',True,2000,102)
 assert r.runtime('a')['success_latency_ms']==1300

def test_success_latency_migration_seeds_only_uncontaminated_history(tmp_path):
 import sqlite3
 path=tmp_path/'r.db'
 r=SQLiteRoutingPolicy(path)
 r.record_runtime('CHAT','clean',True,900,100)
 r.record_runtime('CHAT','mixed',True,700,100);r.record_runtime('CHAT','mixed',False,5,101)
 with sqlite3.connect(path) as db:
  db.execute('ALTER TABLE route_runtime RENAME TO old_runtime')
  db.execute('CREATE TABLE route_runtime(function TEXT NOT NULL,binding TEXT NOT NULL,successes INTEGER NOT NULL,failures INTEGER NOT NULL,latency_ms REAL,updated_at REAL NOT NULL,last_success_at REAL,last_failure_at REAL,consecutive_failures INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(function,binding))')
  db.execute('INSERT INTO route_runtime SELECT function,binding,successes,failures,latency_ms,updated_at,last_success_at,last_failure_at,consecutive_failures FROM old_runtime')
  db.execute('DROP TABLE old_runtime')
 r=SQLiteRoutingPolicy(path)
 assert r.runtime('clean')['success_latency_ms']==900
 assert r.runtime('mixed')['success_latency_ms'] is None

def test_failure_only_route_is_not_promoted_as_unknown_success_quality(tmp_path,monkeypatch):
 import ai_foundation.routing as m
 monkeypatch.setattr(m.time,'time',lambda:5000.0)
 r=SQLiteRoutingPolicy(tmp_path/'r.db');states=[c('working'),c('failure-only')];r.optimize('CHAT',states)
 r.record_runtime('CHAT','working',True,700,4900)
 for n in range(3):r.record_runtime('CHAT','failure-only',False,5,100+n)
 assert r.choose('CHAT',states)=='working'

def test_unobserved_route_does_not_receive_synthetic_exploration_traffic(tmp_path,monkeypatch):
 import ai_foundation.routing as m
 monkeypatch.setattr(m.time,'time',lambda:5000.0)
 r=SQLiteRoutingPolicy(tmp_path/'r.db');states=[c('working'),c('never-tried')];r.optimize('CHAT',states)
 for n in range(3):r.record_runtime('CHAT','working',True,700,4900+n)
 assert r.choose('CHAT',states)=='working'


def test_phase_runtime_is_observation_only_and_does_not_change_policy_choice(tmp_path):
 r=SQLiteRoutingPolicy(tmp_path/'r.db');states=[c('a'),c('b')];r.optimize('CHAT',states)
 r.record_runtime('CHAT','a',True,100,now=100);r.record_runtime('CHAT','b',True,200,now=100)
 before=r.choose('CHAT',states);r.record_phase_runtime('CHAT','FINAL','a',False,30000,now=101);r.record_phase_runtime('CHAT','FINAL','b',True,500,now=101)
 assert r.choose('CHAT',states)==before=='a'
 assert r.phase_runtime('a','FINAL')['failures']==1
 assert r.phase_runtime('b','FINAL')['success_latency_ms']==500
 assert r.get('CHAT').primary=='a'


def test_phase_evidence_never_changes_chat_execution_selection(tmp_path):
 r=SQLiteRoutingPolicy(tmp_path/'r.db');states=[c('a'),c('b')];r.optimize('CHAT',states)
 r.record_runtime('CHAT','a',True,100,now=100);r.record_runtime('CHAT','b',True,200,now=100)
 before=r.choose('CHAT',states)
 r.record_phase_runtime('CHAT','FINAL','a',True,30000,now=101);r.record_phase_runtime('CHAT','FINAL','b',True,500,now=101)
 assert before=='a'
 assert r.choose('CHAT',states,phase='FINAL')=='a'
 assert r.get('CHAT').primary=='a'

def test_single_phase_observation_is_telemetry_only(tmp_path):
 r=SQLiteRoutingPolicy(tmp_path/'r.db');states=[c('a'),c('b')];r.optimize('CHAT',states)
 r.record_runtime('CHAT','a',True,100,now=100);r.record_runtime('CHAT','b',True,200,now=100)
 r.record_phase_runtime('CHAT','FINAL','b',True,500,now=101)
 assert r.choose('CHAT',states,phase='FINAL')=='a'
 assert r.phase_runtime('b','FINAL')['success_latency_ms']==500


def test_larger_observed_quota_wins_over_faster_route(tmp_path):
 r=SQLiteRoutingPolicy(tmp_path/'r.db');r.optimize('CHAT',[c('a'),c('b')])
 r.record_runtime('CHAT','a',True,100,now=100);r.record_runtime('CHAT','b',True,5000,now=100)
 assert r.choose('CHAT',[c('a',s=10,l=10),c('b',s=500,l=500)])=='b'


def test_unobserved_quota_yields_to_observed_quota(tmp_path):
 r=SQLiteRoutingPolicy(tmp_path/'r.db');r.optimize('CHAT',[c('a'),c('b')])
 r.record_runtime('CHAT','a',True,100,now=100);r.record_runtime('CHAT','b',True,5000,now=100)
 a={'binding':'a','health':'ONLINE'}
 assert r.choose('CHAT',[a,c('b',s=50,l=50)])=='b'


def test_recent_failure_still_yields_despite_larger_quota(tmp_path,monkeypatch):
 import ai_foundation.routing as m
 now=[1000.0];monkeypatch.setattr(m.time,'time',lambda:now[0])
 r=SQLiteRoutingPolicy(tmp_path/'r.db');r.optimize('CHAT',[c('a'),c('b')])
 r.record_runtime('CHAT','a',True,100,900);r.record_runtime('CHAT','b',True,200,900)
 r.record_runtime('CHAT','a',False,30000,1000)
 assert r.choose('CHAT',[c('a',s=900,l=900),c('b',s=10,l=10)])=='b'
