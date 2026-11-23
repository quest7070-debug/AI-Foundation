"""No-inference Strata diagnostic contract: current online, offline and fail closed."""
from types import SimpleNamespace

from scripts import m1_selfdev_release_preflight as preflight
from scripts import m1_strata_runtime_probe as probe


SHA = "c" * 40
ENV = {"GITHUB_EVENT_NAME": "pull_request",
       "GITHUB_REPOSITORY": preflight.REPO}


def event(sha=SHA, number=1419):
    return {"action": "synchronize", "pull_request": {
        "number": number, "user": {"login": preflight.OWNER},
        "head": {"ref": preflight.PR_BRANCH, "sha": sha,
                 "repo": {"full_name": preflight.REPO}}}}


def row(**kwargs):
    defaults = {"binding": probe.REQUIRED_BINDING, "health": "ONLINE",
                "active": True, "same_host": False, "model": probe.REQUIRED_MODEL,
                "capabilities": ("CHAT", "CODE"), "reason": None}
    return SimpleNamespace(**{**defaults, **kwargs})


def endpoint(*candidates, model=probe.REQUIRED_MODEL):
    class Discovery:
        def candidates(self):
            return candidates
    return ("local:mainpc-strata", Discovery(),
            SimpleNamespace(models={"code-agent": model}))


def test_live_current_model_discovery_is_not_code_execution():
    result = probe.owner_probe(event(), ENV, SHA, system="Darwin",
        machine="arm64", uid=501, euid=501,
        endpoint_loader=lambda: (endpoint(row()),))
    assert result == {
        "status": "STRATA_CODE_DISCOVERED", "reason": "NONE",
        "strata_code_online": True, "source_sha": SHA,
        "remote_code_execution_proven": False,
        "owner_review_created": False, "model_calls": 0, "service_mutations": 0,
    }


def test_no_credential_offline_or_wrong_model_never_claims_available():
    assert probe.classify_configured_endpoints(())["reason"] == (
        "EXACT_CONFIG_OR_OWNER_KEY_UNAVAILABLE")
    assert probe.classify_configured_endpoints((endpoint(row(), model="other"),))[
        "status"] == "STRATA_NOT_CURRENTLY_SELECTABLE"
    assert probe.classify_configured_endpoints(
        (endpoint(row(health="UNAVAILABLE",active=False,
                      reason="URLError")),))["reason"] == "URLError"
    for changed in (
        row(same_host=True), row(active=False),
        row(capabilities=("CHAT",)), row(model="unapproved"),
    ):
        assert probe.classify_configured_endpoints((endpoint(changed),))[
            "strata_code_online"] is False


def test_owner_head_and_identity_are_mandatory_before_any_network_read():
    def forbidden():
        raise AssertionError("MUST_NOT_TOUCH_OWNER_CONFIG")
    kwargs = dict(event=event(), env=ENV, current_sha=SHA,
                  system="Darwin", machine="arm64", uid=501, euid=501,
                  endpoint_loader=forbidden)
    assert probe.owner_probe(**{**kwargs, "event": event(number=1422)})[
        "status"] == "BLOCKED"
    assert probe.owner_probe(**{**kwargs, "uid": 502})["status"] == "BLOCKED"
    assert probe.owner_probe(**{**kwargs, "current_sha": "d" * 40})[
        "status"] == "BLOCKED"


def test_failed_discovery_has_no_credential_or_internal_error_leak():
    class Failed:
        def candidates(self):
            raise RuntimeError("PRIVATE_API_KEY_AND_HOST_PATH")
    result = probe.classify_configured_endpoints((
        ("local:mainpc-strata", Failed(), SimpleNamespace(
            models={"code-agent": probe.REQUIRED_MODEL})),))
    assert result["reason"] == "MODEL_DISCOVERY_UNVERIFIED"
    assert "PRIVATE_API_KEY" not in str(result)
    assert result["model_calls"] == 0
