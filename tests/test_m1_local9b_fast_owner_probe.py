"""Model-free acceptance tests for the fast, direct M1 pinned 9B probe."""
from scripts import m1_local9b_fast_owner_probe as probe


def tags():
    return {"models": [{"name": probe.MODEL, "digest": probe.DIGEST}]}


def ps(name=None, digest=None):
    return {"models": [] if name is None else [
        {"name": name, "digest": digest or probe.DIGEST}]}


def test_only_installed_pinned_9b_or_exact_resident_is_admitted():
    assert probe.exact_model_state(tags(), ps()) == "READY_COLD_START_CHECK"
    assert probe.exact_model_state(tags(), ps(probe.MODEL)) == "READY_EXISTING_9B"
    assert probe.exact_model_state(tags(), ps("qwen3.5:4b")) == "BLOCKED_OTHER_RESIDENT_MODEL"
    assert probe.exact_model_state(tags(), ps(probe.MODEL, "wrong")) == "BLOCKED_OTHER_RESIDENT_MODEL"
    assert probe.exact_model_state({"models": []}, ps()) == "BLOCKED_PINNED_9B_NOT_INSTALLED"


def test_fixed_public_text_request_exact_9b_with_one_model_call(monkeypatch):
    class Lease:
        def hold(self, **_):
            from contextlib import nullcontext
            return nullcontext()
    monkeypatch.setattr(probe, "HostComputeLease", Lease)
    observed = []
    def transport(path, payload=None, **kwargs):
        observed.append((path, payload))
        if path == "/api/tags":
            return tags()
        if path == "/api/ps":
            return ps()
        assert path == "/api/chat"
        assert payload["model"] == probe.MODEL
        assert payload["keep_alive"] == "2m"
        assert payload["messages"][0]["content"].endswith("and nothing else.")
        return {"model": probe.MODEL, "done": True, "done_reason": "stop",
                "message": {"content": probe.ANSWER}}
    result = probe.fixed_probe(
        transport=transport, admission=lambda: (True, "AVAILABLE"))
    assert result["status"] == "LIVE_PINNED_9B_ANSWER"
    assert result["model_calls"] == 1
    assert result["humanmodel_e2e"] is False
    assert [p for p, _ in observed] == ["/api/tags", "/api/ps", "/api/chat"]
    assert probe.ANSWER not in repr(result)


def test_cpu_pressure_bounded_and_recovers_only_after_recheck(monkeypatch):
    class Lease:
        def hold(self, **_):
            from contextlib import nullcontext
            return nullcontext()
    monkeypatch.setattr(probe, "HostComputeLease", Lease)
    state = {"elapsed": 0, "checks": 0}
    def admission():
        state["checks"] += 1
        return (False, "CPU_PRESSURE") if state["checks"] <= 2 else (True, "AVAILABLE")
    def transport(path, payload=None, **kwargs):
        if path == "/api/tags":
            return tags()
        if path == "/api/ps":
            return ps()
        return {"model": probe.MODEL, "done": True, "done_reason": "stop",
                "message": {"content": probe.ANSWER}}
    result = probe.fixed_probe(
        transport=transport, admission=admission,
        now=lambda: state["elapsed"],
        sleep=lambda t: state.__setitem__("elapsed", state["elapsed"] + t))
    assert result["status"] == "LIVE_PINNED_9B_ANSWER"
    assert state == {"elapsed": 30, "checks": 3}


def test_other_model_does_not_launch_or_wait(monkeypatch):
    class Lease:
        def hold(self, **_):
            from contextlib import nullcontext
            return nullcontext()
    monkeypatch.setattr(probe, "HostComputeLease", Lease)
    calls = []
    def transport(path, payload=None, **kw):
        calls.append(path)
        if path == "/api/tags":
            return tags()
        if path == "/api/ps":
            return ps("qwen3.5:4b")
        raise AssertionError("never infer")
    result = probe.fixed_probe(transport=transport,
                               admission=lambda: (_ for _ in ()).throw(AssertionError()),
                               sleep=lambda t: (_ for _ in ()).throw(AssertionError()))
    assert result == {"status": "BLOCKED", "reason": "BLOCKED_OTHER_RESIDENT_MODEL",
                      "model_calls": 0}
    assert calls == ["/api/tags", "/api/ps"]


def test_owner_issue_rejects_changed_body_and_other_actors():
    issue = {"number": 123, "state": "open", "title": probe.TITLE,
             "body": probe.BODY, "user": {"login": probe.OWNER}}
    event = {"action": "opened", "repository": {"full_name": probe.REPO},
             "sender": {"login": probe.OWNER}, "issue": issue}
    assert probe.owner_issue(event, issue)
    assert not probe.owner_issue(event, {**issue, "body": "arbitrary command"})
    assert not probe.owner_issue({**event, "sender": {"login": "outsider"}}, issue)
