from ai_foundation.long_term_health import check_long_term_health

def test_long_term_health_reports_bounded_signals(tmp_path):
 (tmp_path/'local-compute').mkdir();(tmp_path/'local-compute'/'llama-swap.log').write_bytes(b'x'*10)
 h=check_long_term_health(tmp_path,disk_warn_free_bytes=1,llama_log_warn_bytes=20,handoff_warn_bytes=20,clock=lambda:123)
 assert h.ok and h.checked_at==123
 assert any(x.name=='llama-swap-log' and x.ok for x in h.signals)

def test_long_term_health_flags_growth_without_deleting(tmp_path):
 (tmp_path/'local-compute').mkdir();p=tmp_path/'local-compute'/'llama-swap.log';p.write_bytes(b'x'*21)
 h=check_long_term_health(tmp_path,disk_warn_free_bytes=1,llama_log_warn_bytes=20)
 assert not h.ok and p.stat().st_size==21
 assert next(x for x in h.signals if x.name=='llama-swap-log').ok is False

def test_health_loop_keeps_latest_without_cleanup():
 from ai_foundation.long_term_health import LongTermHealthLoop,LongTermHealth,LongTermSignal
 seen=[]
 def check():
  seen.append(1);return LongTermHealth(len(seen),(LongTermSignal('x',len(seen)>1,str(len(seen))),))
 loop=LongTermHealthLoop(check,interval=60)
 assert loop.latest() is None
 assert loop.tick().ok is False
 assert loop.tick().ok is True
 assert loop.latest().checked_at==2

def test_evidence_store_is_single_atomic_bounded_record(tmp_path):
 from ai_foundation.long_term_health import LongTermHealthEvidenceStore,LongTermHealth,LongTermSignal
 p=tmp_path/'health.json';store=LongTermHealthEvidenceStore(p)
 for n in range(100): store.save(LongTermHealth(n,(LongTermSignal('x',n==99,str(n)),)))
 assert len(list(tmp_path.iterdir()))==1
 assert store.load().checked_at==99 and store.load().ok
 assert p.stat().st_size<1024

def test_corrupt_evidence_fails_to_no_claim(tmp_path):
 from ai_foundation.long_term_health import LongTermHealthEvidenceStore
 p=tmp_path/'health.json';p.write_text('{broken')
 assert LongTermHealthEvidenceStore(p).load() is None

def test_stale_ok_is_not_trustworthy():
 from ai_foundation.long_term_health import LongTermHealthLoop,LongTermHealth,LongTermSignal
 now=[100.0]
 loop=LongTermHealthLoop(lambda:LongTermHealth(now[0],(LongTermSignal('x',True,'ok'),)),interval=60,clock=lambda:now[0])
 loop.tick();assert loop.ok()
 now[0]=221.0;assert loop.trustworthy() is None and loop.ok() is False

def test_future_dated_health_is_not_trustworthy():
 from ai_foundation.long_term_health import LongTermHealthLoop,LongTermHealth,LongTermSignal
 loop=LongTermHealthLoop(lambda:LongTermHealth(200,(LongTermSignal('x',True,'ok'),)),interval=60,clock=lambda:100)
 loop.tick();assert loop.ok() is False

def test_unhealthy_fresh_evidence_remains_trustworthy_but_not_ok():
 from ai_foundation.long_term_health import LongTermHealthLoop,LongTermHealth,LongTermSignal
 loop=LongTermHealthLoop(lambda:LongTermHealth(100,(LongTermSignal('x',False,'bad'),)),interval=60,clock=lambda:100)
 loop.tick();assert loop.trustworthy() is not None and loop.ok() is False


def test_health_observes_trace_push_and_evidence_sizes_without_content(tmp_path):
 (tmp_path/'remote').mkdir();(tmp_path/'trace.jsonl').write_text('SECRET USER CONTENT');(tmp_path/'remote'/'push-seen.json').write_text('["key"]');(tmp_path/'long-term-health.json').write_text('{}')
 h=check_long_term_health(tmp_path,disk_warn_free_bytes=1,trace_warn_bytes=100,push_state_warn_bytes=100)
 by={x.name:x for x in h.signals};assert by['foundation-trace'].ok and by['push-dedup-state'].ok and by['health-evidence'].ok
 assert 'SECRET' not in repr(h) and all('bytes' in by[n].detail for n in ('foundation-trace','push-dedup-state','health-evidence'))
