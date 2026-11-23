from ai_foundation.containment import *
class P:
 def __init__(self,healthy=True,fail=False): self.healthy=healthy; self.fail=fail; self.starts=0; self.stops=0
 def start(self): self.starts+=1; (_ for _ in ()).throw(RuntimeError()) if self.fail else None
 def health(self): return self.healthy
 def stop(self): self.stops+=1
def test_ready_is_health_checked_and_idempotent():
 p=P(); c=ContainmentLifecycle(p); assert c.ensure_ready(); assert c.ensure_ready(); assert p.starts==1
def test_unhealthy_or_start_failure_fails_closed():
 assert not ContainmentLifecycle(P(False)).ensure_ready()
 assert not ContainmentLifecycle(P(fail=True)).ensure_ready()
def test_shutdown_always_marks_stopped():
 p=P(); c=ContainmentLifecycle(p); c.ensure_ready(); c.shutdown(); assert c.state is ContainmentState.STOPPED and p.stops==1

def test_health_exception_fails_closed():
 class Bad(P):
  def health(self): raise RuntimeError('down')
 c=ContainmentLifecycle(Bad()); assert not c.ensure_ready() and c.state is ContainmentState.FAILED

def test_toolhive_adapter_parses_lifecycle(monkeypatch,tmp_path):
 import subprocess
 from ai_foundation.containment import ToolHiveContainmentPort
 calls=[]
 def run(args,**kw):
  calls.append(args[-1]); return subprocess.CompletedProcess(args,0,'Status: running','')
 monkeypatch.setattr(subprocess,'run',run)
 p=ToolHiveContainmentPort(tmp_path/'lifecycle.sh'); p.start(); assert p.health(); p.stop(); assert calls==['ensure','status','stop']
