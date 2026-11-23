"""No-effect contract for the M1 fixed Mongo owner-count bridge."""
import json
import subprocess
import pytest

from scripts import m1_docker_owner_count_probe as probe
from scripts.m1_development_bridge import parse_request


def test_owner_count_exact_issue_operation():
    assert parse_request(
        "Foundation M1 Bridge: owner-count",
        '<!-- foundation-m1-bridge: {"version":1,"operation":"owner-count"} -->',
    ) == "owner-count"
    with pytest.raises(Exception):
        parse_request(
            "Foundation M1 Bridge: owner-count",
            '<!-- foundation-m1-bridge: {"version":1,"operation":"owner-count","exec":"bash"} -->',
        )


@pytest.mark.parametrize("count,band,single", [
    (0, "ZERO", False), (1, "ONE", True), (2, "MULTIPLE", False),
])
def test_fixed_bounded_query_never_exports_user_id(monkeypatch, count, band, single):
    monkeypatch.setattr(probe, "require_m1", lambda: None)
    private = "PRIVATE-ACCOUNT-ID"
    def run(args, **kw):
        assert args[:7] == ["docker", "exec", "chat-mongodb", "mongosh",
                            "--quiet", "LibreChat", "--eval"]
        assert "limit(2)" in args[7] and "print(JSON.stringify({count:n}))" in args[7]
        assert kw["timeout"] == 12 and kw["check"] is True
        return subprocess.CompletedProcess(
            args, 0, json.dumps({"count": count}), private)
    monkeypatch.setattr(probe.subprocess, "run", run)
    status = probe.owner_count_status(docker="docker")
    assert status["status"] == "OBSERVED"
    assert status["account_count_band"] == band
    assert status["single_server_account"] is single
    assert status["service_mutations"] == status["native_dispatches"] == 0
    assert private not in json.dumps(status)


@pytest.mark.parametrize("output", [
    '{"count":"1"}', '{"count":3}', '{"count":true}',
    '{"count":1,"owner":"private"}\n{"count":1}', "bad-json",
])
def test_bad_untrusted_mongosh_output_is_not_promoted(monkeypatch, output):
    monkeypatch.setattr(probe, "require_m1", lambda: None)
    monkeypatch.setattr(probe.subprocess, "run", lambda args, **kw:
                        subprocess.CompletedProcess(args, 0, output, "private"))
    status = probe.owner_count_status(docker="docker")
    assert status["status"] == "BLOCKED"
    assert status["single_server_account"] is None
    assert status["account_count_band"] is None
    assert "private" not in json.dumps(status)


def test_connection_failure_redacts_exception_and_classifies_fixed_state(monkeypatch):
    monkeypatch.setattr(probe, "require_m1", lambda: None)
    def failed(args, **kw):
        raise subprocess.CalledProcessError(1, args, output="PRIVATE-SERVER")
    monkeypatch.setattr(probe.subprocess, "run", failed)
    monkeypatch.setattr(probe, "_owner_service_state", lambda _: "DOCKER_DAEMON_INACCESSIBLE")
    status = probe.owner_count_status(docker="docker")
    assert status["owner_service_state"] == "DOCKER_DAEMON_INACCESSIBLE"
    assert status["status"] == "BLOCKED"
    assert status["single_server_account"] is None
    assert "PRIVATE" not in json.dumps(status)
