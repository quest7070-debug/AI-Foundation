"""Deterministic no-network/no-Docker test of the native container contract."""
import json
from types import SimpleNamespace

import pytest

from ai_foundation.agent import AgentRequest
from ai_foundation.harness_public_canary import PUBLIC_CANARY_PROMPT
from ai_foundation.opencode_docker_isolation import (
    OfflineOpenCodeContainerCanaryAgent,
    accept_container_canary,
    docker_offline_plan,
    _worker,
)

IMAGE = "sha256:" + "a" * 64
BINARY = "b" * 64


def outcome(stdout=b"", code=0):
    return SimpleNamespace(stdout=stdout, returncode=code)


def test_docker_plan_is_kernel_network_none_no_host_mounts_or_keys():
    plan = docker_offline_plan(IMAGE, BINARY)
    argv = plan["argv"]
    assert plan["execution_authorized"] is False
    assert "--network=none" in argv
    assert "--platform=linux/arm64" in argv
    assert "--pull=never" in argv
    assert "--read-only" in argv
    assert "--cap-drop=ALL" in argv
    assert "--security-opt=no-new-privileges" in argv
    assert "--ipc=none" in argv
    assert "--user=65534:65534" in argv
    assert all(not a.startswith(("--volume", "-v", "--mount",
                                "--privileged", "--network=host",
                                "--env-file")) for a in argv)
    assert argv[-2:] == ["--worker", BINARY]
    assert IMAGE in argv and BINARY in argv
    assert "GROQ_API_KEY" not in json.dumps(plan)
    assert "OPENCODE_API_KEY" not in json.dumps(plan)
    assert "GITHUB_TOKEN" not in json.dumps(plan)


def test_missing_pinned_image_or_binary_never_starts_docker():
    attempts = []
    def fake_runner(*args, **kw):
        attempts.append(args)
        raise AssertionError("should never launch")
    for image, binary in (
        (None, BINARY), ("ubuntu:latest", BINARY),
        (IMAGE, None), (IMAGE, "abc"), ("sha256:" + "Z" * 64, BINARY),
    ):
        r = accept_container_canary(image, binary, runner=fake_runner)
        assert r["accepted"] is False and r["attempted"] is False
    assert attempts == []


def test_local_image_is_inspected_before_one_run_and_report_verified():
    calls = []
    def fake_runner(argv, **kwargs):
        calls.append((argv, kwargs))
        assert kwargs["env"].keys() == {"PATH", "HOME"}
        assert kwargs["stdin"] is not None
        if argv[1:3] == ["image", "inspect"]:
            assert argv[-1] == IMAGE
            return outcome((IMAGE + "\n").encode())
        assert argv[1] == "run"
        assert "--network=none" in argv
        assert "--pull=never" in argv
        return outcome(json.dumps({
            "status": "VERIFIED_OFFLINE_CLI_PUBLIC_FIXTURE",
            "accepted": True, "gateway_accepted": 1,
            "gateway_denied": 0, "outside_inference_calls": 0,
            "binary_sha256": BINARY, "version": "2.2.0",
        }).encode())
    r = accept_container_canary(IMAGE, BINARY, runner=fake_runner)
    # A mock Docker executable is NOT kernel/host evidence.
    assert r == {"status": "OPENCODE_SYNTHETIC_RUNNER_ONLY",
                 "accepted": False, "attempted": True,
                 "gateway_accepted": 1, "gateway_denied": 0,
                 "outside_inference_calls": 0}
    assert len(calls) == 2


@pytest.mark.parametrize("change", [
    {"gateway_denied": 1},
    {"gateway_accepted": 0},
    {"status": "OPENCODE_FIXTURE_NOT_ACCEPTED"},
    {"binary_sha256": "c" * 64},
    {"version": "1.0.0"},
    {"outside_inference_calls": 1},
    {"accepted": False},
])
def test_paid_helper_or_untrusted_container_result_does_not_pass(change):
    base = {"status": "VERIFIED_OFFLINE_CLI_PUBLIC_FIXTURE",
            "accepted": True, "gateway_accepted": 1,
            "gateway_denied": 0, "outside_inference_calls": 0,
            "binary_sha256": BINARY, "version": "2.2.0"}
    def fake_runner(argv, **kwargs):
        if argv[1] == "image":
            return outcome(IMAGE.encode())
        return outcome(json.dumps({**base, **change}).encode())
    r = accept_container_canary(IMAGE, BINARY, runner=fake_runner)
    assert r["accepted"] is False


def test_non_local_image_digest_and_timeout_never_claim_acceptance():
    def wrong_image(argv, **kwargs):
        return outcome(("sha256:" + "c" * 64).encode())
    r = accept_container_canary(IMAGE, BINARY, runner=wrong_image)
    assert r["status"] == "OPENCODE_PINNED_IMAGE_NOT_LOCAL"
    assert r["attempted"] is False

    def timed_out(argv, **kwargs):
        if argv[1] == "image":
            return outcome(IMAGE.encode())
        raise TimeoutError("bounded native process uncertainty")
    r = accept_container_canary(IMAGE, BINARY, runner=timed_out)
    assert r["status"] == "OPENCODE_CONTAINER_RUN_UNCERTAIN"
    assert r["accepted"] is False


def test_host_cannot_claim_worker_sandbox_by_setting_one_environment_flag(monkeypatch):
    monkeypatch.setenv("FOUNDATION_OFFLINE_DOCKER_CANARY", "1")
    monkeypatch.setattr("ai_foundation.opencode_docker_isolation.sys.platform",
                        "darwin")
    assert _worker(BINARY)["status"] == "HOST_OS_SANDBOX_NOT_ATTESTED"


def test_no_real_agent_execution_without_installed_pinned_image():
    agent = OfflineOpenCodeContainerCanaryAgent()
    with pytest.raises(ValueError, match="OPENCODE_PUBLIC_FIXTURE_ONLY"):
        agent.run(AgentRequest("private project"))
    with pytest.raises(RuntimeError, match="OPENCODE_CONTAINER_CANARY_NOT_ACCEPTED"):
        agent.run(AgentRequest(PUBLIC_CANARY_PROMPT))


def test_early_worker_rejection_is_safe_and_does_not_claim_e2e():
    def early(argv, **kwargs):
        if argv[1] == "image":
            return outcome(IMAGE.encode())
        return outcome(b'{"status":"OPENCODE_V2_BINARY_REQUIRED"}')

    result = accept_container_canary(IMAGE, BINARY, runner=early)
    assert result == {
        "status": "OPENCODE_CONTAINER_REPORT_UNVERIFIED",
        "worker_status": "OPENCODE_V2_BINARY_REQUIRED",
        "sandbox_detail": "NOT_REPORTED",
        "accepted": False, "attempted": True,
    }

    def hostile(argv, **kwargs):
        if argv[1] == "image":
            return outcome(IMAGE.encode())
        return outcome(b'{"status":"private credentials here"}')

    bad = accept_container_canary(IMAGE, BINARY, runner=hostile)
    assert bad["worker_status"] == "UNRECOGNIZED"
    assert bad["accepted"] is False


def test_worker_checks_actual_net_namespace_not_sysfs_listing(monkeypatch):
    monkeypatch.setenv("FOUNDATION_OFFLINE_DOCKER_CANARY", "1")
    monkeypatch.setattr("ai_foundation.opencode_docker_isolation.sys.platform", "linux")
    monkeypatch.setattr("ai_foundation.opencode_docker_isolation.os.getuid",
                        lambda: 65534)
    # Actual net namespace has an external interface, so stay denied.
    monkeypatch.setattr("ai_foundation.opencode_docker_isolation.socket.if_nameindex",
                        lambda: [(1, "lo"), (2, "eth0")])
    outcome = _worker(BINARY)
    assert outcome["status"] == "HOST_OS_SANDBOX_NOT_ATTESTED"
    assert outcome["sandbox_detail"] == "NONLO_NETWORK_INTERFACE"


def test_builtin_kernel_tunnel_links_require_down_unaddressed_unrouted(monkeypatch):
    """Even built-in tunnel interfaces never pass if they can route traffic."""
    import builtins
    import errno
    import io
    from ai_foundation import opencode_docker_isolation as boundary

    monkeypatch.setattr(boundary.socket, "if_nameindex",
                        lambda: [(1, "lo"), (2, "tunl0"), (3, "ip6tnl0")])
    contents = {
        "/proc/net/route": b"Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n",
        "/proc/net/ipv6_route": b"",
        "/proc/net/if_inet6": b"",
    }
    actual_open = builtins.open
    def no_host_file(path, *args, **kwargs):
        if path in contents:
            return io.BytesIO(contents[path])
        return actual_open(path, *args, **kwargs)
    monkeypatch.setattr(builtins, "open", no_host_file)

    class NoNetworkSocket:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def fileno(self):
            return 7
    monkeypatch.setattr(boundary.socket, "socket", lambda *a: NoNetworkSocket())
    state = {"up": False, "addr": False}
    def local_ioctl(fd, code, request):
        assert fd == 7
        if code == 0x8913:
            b = bytearray(request)
            if state["up"]:
                b[16] = 1
            return bytes(b)
        assert code == 0x8915
        if state["addr"]:
            return request
        raise OSError(errno.EADDRNOTAVAIL, "no IPv4 address")
    monkeypatch.setattr(boundary.fcntl, "ioctl", local_ioctl)

    assert boundary._netns_isolated() == (True, "NO_ACTIVE_EXTERNAL_LINK")
    state["up"] = True
    assert boundary._netns_isolated() == (False, "NONLO_DEVICE_UP")
    state["up"] = False
    state["addr"] = True
    assert boundary._netns_isolated() == (False, "NONLO_IPV4_ADDRESS")
    state["addr"] = False
    contents["/proc/net/route"] += b"tunl0\t00000000\t00000000\t0001\t0\t0\t0\t00000000\t0\t0\t0\n"
    assert boundary._netns_isolated() == (False, "NONLO_IPV4_ROUTE")
    contents["/proc/net/route"] = contents["/proc/net/route"].splitlines()[0] + b"\n"
    contents["/proc/net/ipv6_route"] = b"0 0 0 0 0 0 0 0 0 ip6tnl0\n"
    assert boundary._netns_isolated() == (False, "NONLO_IPV6_ROUTE")
    contents["/proc/net/ipv6_route"] = b""
    contents["/proc/net/if_inet6"] = b"0 0 0 0 0 ip6tnl0\n"
    assert boundary._netns_isolated() == (False, "NONLO_IPV6_ADDRESS")
