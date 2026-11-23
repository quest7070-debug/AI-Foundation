from dataclasses import dataclass
from enum import Enum
import subprocess
from pathlib import Path
class ContainmentState(str,Enum): STOPPED='STOPPED'; STARTING='STARTING'; READY='READY'; FAILED='FAILED'
class ContainmentPort:
 def start(self): ...
 def health(self)->bool: ...
 def stop(self): ...
@dataclass
class ContainmentLifecycle:
 port: object
 state: ContainmentState=ContainmentState.STOPPED
 def ensure_ready(self):
  try:
   if self.state is ContainmentState.READY and self.port.health(): return True
  except Exception: self.state=ContainmentState.FAILED; return False
  self.state=ContainmentState.STARTING
  try: self.port.start(); healthy=self.port.health()
  except Exception: self.state=ContainmentState.FAILED; return False
  self.state=ContainmentState.READY if healthy else ContainmentState.FAILED
  return self.state is ContainmentState.READY
 def shutdown(self):
  try: self.port.stop()
  finally: self.state=ContainmentState.STOPPED
class ToolHiveContainmentPort:
 def __init__(self,script:str|Path,env=None): self.script=str(script); self.env=env
 def _run(self,action,timeout): return subprocess.run([self.script,action],env=self.env,capture_output=True,text=True,timeout=timeout)
 def start(self):
  cp=self._run('ensure',60)
  if cp.returncode: raise RuntimeError('containment start failed')
 def health(self):
  try: cp=self._run('status',15)
  except (OSError,subprocess.SubprocessError): return False
  return cp.returncode==0 and 'running' in (cp.stdout+cp.stderr).lower()
 def stop(self):
  cp=self._run('stop',30)
  if cp.returncode: raise RuntimeError('containment stop failed')
