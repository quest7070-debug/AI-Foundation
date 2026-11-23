import sqlite3
from ai_foundation.preflight import preflight
from ai_foundation.productization import FoundationConfig

def test_cached_integrity_check_is_one_flight_and_fails_closed_during_refresh():
    from threading import Event, Thread
    from time import monotonic
    from ai_foundation.preflight import CachedPreflight, Check, PreflightReport

    now = [100.0]
    entered, released = Event(), Event()
    calls = []
    def slow_integrity():
        calls.append("full-integrity-check")
        entered.set()
        assert released.wait(3)
        return PreflightReport((Check("database:guard.db", True, "ok"),))

    read = CachedPreflight(slow_integrity, clock=lambda: now[0])
    first = []
    worker = Thread(target=lambda: first.append(read()), daemon=True)
    worker.start()
    try:
        assert entered.wait(2)
        begin = monotonic()
        pending = read()
        assert pending.ready is False
        assert pending.checks[0].detail == "integrity-check-in-progress"
        assert monotonic() - begin < 1
        assert calls == ["full-integrity-check"]
    finally:
        released.set()
        worker.join(timeout=3)
    assert not worker.is_alive()
    assert first[0].ready is True
    assert read() is first[0]
    assert calls == ["full-integrity-check"]
    now[0] = 130.0
    assert read().ready is True
    assert calls == ["full-integrity-check", "full-integrity-check"]


def test_preflight_reports_new_host_without_mutating(tmp_path):
    c=FoundationConfig(str((tmp_path/'data').resolve())); r=preflight(c)
    assert any(x.name=='config' and x.ok for x in r.checks)
    assert not (tmp_path/'data').exists()

def test_preflight_detects_corrupt_db(tmp_path):
    root=tmp_path/'data'; root.mkdir(); (root/'guard.db').write_bytes(b'bad db')
    r=preflight(FoundationConfig(str(root.resolve())))
    assert any(x.name=='database:guard.db' and not x.ok for x in r.checks)

def test_required_credential_is_read_only_availability_gate(tmp_path):
    class C:
        def __init__(self,ok): self.ok=ok; self.calls=[]
        def available(self,b): self.calls.append(b); return self.ok
    c=C(False); r=preflight(FoundationConfig(str((tmp_path/'data').resolve())),c,('prod-api',))
    assert c.calls==['prod-api'] and any(x.name=='credential:prod-api' and not x.ok for x in r.checks)

def test_preflight_checks_all_foundation_databases(tmp_path):
 from ai_foundation.productization import FoundationConfig
 from ai_foundation.preflight import preflight
 c=FoundationConfig(str(tmp_path.resolve()))
 # A corrupt optional-state database must make readiness false rather than disappear behind an empty UI.
 (tmp_path/c.routing_db).write_bytes(b'not sqlite')
 r=preflight(c);rows={x.name:x for x in r.checks}
 assert not r.ready and rows['database:'+c.routing_db].ok is False
 assert {'database:'+x for x in (c.guard_db,c.work_db,c.provider_db,c.routing_db,c.reconciliation_db)} <= set(rows)
