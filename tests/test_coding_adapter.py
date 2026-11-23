from pathlib import Path
import pytest
from ai_foundation.coding_adapter import PytestPort,build_coding_specialist
from ai_foundation.capability_request import CapabilityRequest
from ai_foundation.guard import GuardCore
from ai_foundation.core import GuardState

class Port:
 def observe(self,p): return Path(p.target).read_text()
 def execute(self,p): Path(p.target).write_text(p.text)

def test_build_binds_repo_and_rejects_escape(tmp_path):
 repo=tmp_path/"repo"; repo.mkdir(); (repo/"a.txt").write_text("a")
 s=build_coding_specialist(CapabilityRequest("CODE",repo_root=str(repo)),GuardCore(GuardState()),Port(),"r")
 assert s.tools.read("a.txt")=="a"
 with pytest.raises(PermissionError): s.tools.read("../outside")

def test_wrong_capability_rejected(tmp_path):
 with pytest.raises(ValueError): build_coding_specialist(CapabilityRequest(),GuardCore(GuardState()),Port(),"r")

def test_pytest_port_uses_bound_repo_and_no_shell(tmp_path,monkeypatch):
 repo=tmp_path/"repo"; repo.mkdir(); seen={}
 class CP: returncode=0; stdout="1 passed"; stderr=""
 def fake(args,**kw): seen["args"]=args;seen.update(kw);return CP()
 monkeypatch.setattr("ai_foundation.coding_adapter.subprocess.run",fake)
 out=PytestPort(str(repo)).run_tests("")
 assert out=="1 passed" and seen["cwd"]==str(repo) and "shell" not in seen and seen["args"][-1]==str(repo)
 with pytest.raises(PermissionError): PytestPort(str(repo)).run_tests("../outside")


def test_code_change_rejects_protected_target(tmp_path):
 from ai_foundation.protected_resources import ProtectedResources
 repo=tmp_path/'repo';repo.mkdir()
 target=repo/'llama-swap.yaml';target.write_text('old')
 protected=ProtectedResources()
 s=build_coding_specialist(
  CapabilityRequest('CODE',repo_root=str(repo)),
  GuardCore(GuardState()),Port(),'r',protected=protected)
 class Pass:
  def run_tests(self,target): return 'pass'
 s.tests=Pass()
 with pytest.raises(PermissionError):
  s.apply_verified_change('llama-swap.yaml','new')
 assert target.read_text()=='old'
