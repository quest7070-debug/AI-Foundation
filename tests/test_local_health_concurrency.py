from concurrent.futures import ThreadPoolExecutor
from ai_foundation.local_health import LocalFailureCooldown

def test_persistent_cooldown_preserves_independent_concurrent_writers(tmp_path):
 p=tmp_path/'cooldown.sqlite'; now=lambda:100.0
 def fail(name): LocalFailureCooldown(ttl=60,clock=now,path=p).fail(name)
 with ThreadPoolExecutor(max_workers=8) as x:list(x.map(fail,[f'local:{i}' for i in range(32)]))
 assert LocalFailureCooldown(ttl=60,clock=now,path=p).excluded()=={f'local:{i}' for i in range(32)}
 assert oct(p.stat().st_mode & 0o777)=='0o600'


def test_elapsed_ttl_does_not_invent_local_recovery(tmp_path):
 p=tmp_path/'cooldown.sqlite';now=[100.0]
 h=LocalFailureCooldown(ttl=10,clock=lambda:now[0],path=p);h.fail('local:x')
 now[0]=1000.0
 assert LocalFailureCooldown(ttl=10,clock=lambda:now[0],path=p).excluded()=={'local:x'}
 h.success('local:x')
 assert not h.excluded()
