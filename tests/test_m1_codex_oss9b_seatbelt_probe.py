"""Fixed local-network-only Codex seatbelt profile, model-free."""
from pathlib import Path
from scripts import m1_codex_oss9b_seatbelt_probe as p
import pytest


def test_local_only_policy_denies_home_wan_and_ambient_writes(monkeypatch):
    monkeypatch.setattr(Path, "resolve", lambda self, strict=True:self)
    sb=p.policy_for(owner_home=Path("/Users/owner"),
                    workspace=Path("/private/tmp/codex-public-test"))
    assert "(deny network*)" in sb
    assert '(allow network-outbound (remote ip "localhost:11434"))' in sb
    assert '(deny file-read* (subpath "/Users/owner"))' in sb
    assert "(deny file-write*)" in sb
    assert '(allow file-write* (subpath "/private/tmp/codex-public-test"))' in sb
    assert 'api.openai.com' not in sb


@pytest.mark.parametrize("owner,work",[
    ("/tmp/owner","/private/tmp/a"),
    ("/Users/owner","/Users/owner/child"),
    ("/Users/owner","/tmp/a"),
])
def test_wrong_sandbox_roots_fail_closed(monkeypatch,owner,work):
    monkeypatch.setattr(Path,"resolve",lambda self,strict=True:self)
    with pytest.raises(ValueError,match="CODEX_SANDBOX_BOUNDARY_INVALID"):
        p.policy_for(owner_home=Path(owner),workspace=Path(work))


def test_denied_external_socket_needs_explicit_kernel_permission_error():
    assert "errno.EPERM" in p.PUBLIC_NET_DENY
    assert "errno.EACCES" in p.PUBLIC_NET_DENY
    assert "198.51.100.1" in p.PUBLIC_NET_DENY
    assert "11434" in p.LOCAL_HOST_OK
