"""Model-free tests for pinned Codex OSS + local9B M1 admission."""
from contextlib import contextmanager
from scripts import m1_codex_oss9b_host_admission as guard
from ai_foundation.host_compute_lease import HostComputeBusy
import pytest


class FakeLease:
    def __init__(self, busy=False):self.busy=busy;self.entered=0
    @contextmanager
    def hold(self):
        self.entered+=1
        if self.busy:raise HostComputeBusy("already-in-use")
        yield


def m1(monkeypatch):
    monkeypatch.setattr(guard.platform,"system",lambda:"Darwin")
    monkeypatch.setattr(guard.platform,"machine",lambda:"arm64")
    monkeypatch.setattr(guard.os,"getuid",lambda:501)


def test_no_model_approval_from_admissible_host(monkeypatch):
    m1(monkeypatch)
    lease=FakeLease()
    result=guard.preflight(lease=lease,discover=lambda:object(),
                           model_check=lambda:True,
                           admit=lambda:(True,"AVAILABLE"))
    assert result=={"status":"LOCAL9B_HOST_ADMISSIBLE_NOT_AUTHORIZED",
                    "model_calls":0,"remote_calls":0,
                    "seatbelt_proven":False,"codex_activated":False}
    assert lease.entered==1


@pytest.mark.parametrize("cli,model,busy,admission,expected",[
    (None,True,False,(True,"AVAILABLE"),"CLI_PIN_MISMATCH"),
    ("p",False,False,(True,"AVAILABLE"),"LOCAL9B_DIGEST_UNVERIFIED"),
    ("p",True,True,(True,"AVAILABLE"),"DEFER_LEASE_BUSY"),
    ("p",True,False,(False,"CPU_PRESSURE"),"DEFER_CPU_PRESSURE"),
    ("p",True,False,(False,"MEMORY_PRESSURE"),"DEFER_MEMORY_PRESSURE"),
    ("p",True,False,(False,"UNKNOWN"),"DEFER_RESOURCE_UNKNOWN"),
])
def test_fail_closed_without_calling_a_model(monkeypatch,cli,model,busy,admission,expected):
    m1(monkeypatch)
    result=guard.preflight(lease=FakeLease(busy),discover=lambda:cli,
                           model_check=lambda:model,admit=lambda:admission)
    assert result["status"]==expected
    assert result["model_calls"]==0


def test_non_m1_denied_before_host_lookups(monkeypatch):
    monkeypatch.setattr(guard.platform,"system",lambda:"Linux")
    def forbidden():raise AssertionError("unexpected host lookup")
    result=guard.preflight(discover=forbidden,model_check=forbidden)
    assert result["status"]=="OWNER_M1_REQUIRED"


def test_digest_identity_literals_do_not_select_a_new_model():
    assert guard.MODEL=="qwen3.5:9b"
    assert guard.CLI_SHA256=="61b0194f3bb6534439c8d26a3ed57d0805f84b884588b761795323eeb92fcf70"
    assert guard.MODEL_SHA256=="56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90"
