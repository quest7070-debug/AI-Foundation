from pathlib import Path
import pytest
from ai_foundation.files_adapter import build_files
from ai_foundation.capability_request import CapabilityRequest
from ai_foundation.guard import GuardCore
from ai_foundation.core import GuardState
from ai_foundation.protected_resources import ProtectedResources

class Port:
 def execute(self,p): Path(p.target).write_text(p.text)
 def observe(self,p): return Path(p.target).read_text() if Path(p.target).exists() else ""

def test_read_scope_and_optional_narrow_write(tmp_path):
 read=tmp_path/"read"; write=read/"write"; write.mkdir(parents=True); (read/"a").write_text("A")
 req=CapabilityRequest("FILES",file_read_root=str(read),file_write_root=str(write))
 f=build_files(req,GuardCore(GuardState()),Port())
 assert f.read("r","a")=="A"
 assert f.write("w","b","B")=="VERIFIED_COMPLETE" and (write/"b").read_text()=="B"
 with pytest.raises(PermissionError): f.write("x","../outside","X")

def test_readonly_request_cannot_write(tmp_path):
 req=CapabilityRequest("FILES",file_read_root=str(tmp_path))
 f=build_files(req,GuardCore(GuardState()),Port())
 with pytest.raises(PermissionError): f.write("w","x","X")

def test_protected_write_scope_stays_denied(tmp_path):
 protected=tmp_path/"protected"; protected.mkdir()
 req=CapabilityRequest("FILES",file_read_root=str(tmp_path),file_write_root=str(protected))
 with pytest.raises(PermissionError): build_files(req,GuardCore(GuardState()),Port(),protected=ProtectedResources((str(protected),)))

def test_wrong_capability_rejected(tmp_path):
 with pytest.raises(ValueError): build_files(CapabilityRequest(),GuardCore(GuardState()),Port())
