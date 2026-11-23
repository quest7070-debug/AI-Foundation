"""No-model contract tests for the owner-only M1 synthetic 9B answer probe."""
from __future__ import annotations

import re

import pytest

from scripts import m1_humanmodel_9b_synthetic_e2e as probe


def test_owner_issue_requires_exact_owner_title_body_and_live_readback():
    issue = {"number": 990, "title": probe.TITLE, "body": probe.BODY,
             "state": "open", "user": {"login": "quest7070-debug"}}
    event = {"action": "opened", "repository": {"full_name": probe.REPO},
             "issue": issue}
    assert probe.valid_owner_event(event, issue)
    for name, changed in (
        ("title", "different"),
        ("body", "question=fetch private source"),
        ("state", "closed"),
        ("user", {"login": "different-user"}),
        ("number", True),
    ):
        live = {**issue, name: changed}
        assert not probe.valid_owner_event(event, live)
        assert not probe.valid_owner_event(
            {**event, "issue": {**issue, name: changed}}, issue)


def test_only_exact_pinned_resident_9b_is_eligible():
    tags = {"models": [{"name": probe.MODEL, "digest": probe.MODEL_DIGEST}]}
    ps = {"models": [{"name": probe.MODEL, "digest": probe.MODEL_DIGEST}]}
    assert probe._model_gate(tags, ps) == "READY_EXISTING_9B"
    assert probe._model_gate(
        {"models": [{"name": probe.MODEL, "digest": "untrusted"}]}, ps
    ) == "BLOCKED_PINNED_9B_NOT_INSTALLED"
    assert probe._model_gate(tags, {"models": [
        {"name": "qwen3:4b", "digest": "different"},
    ]}) == "BLOCKED_SHARED_OLLAMA_OTHER_MODEL"


def test_synthetic_source_through_full_agent_and_cited_reply(monkeypatch):
    seen = []
    def fake_local(path, payload=None, *, timeout=3):
        assert path == "/api/chat"
        assert payload["model"] == probe.MODEL
        assert payload["think"] is False
        assert payload["options"]["num_predict"] == 640
        assert timeout == 180
        assert "tools" not in payload
        assert all(row["role"] in {"system", "user"}
                   for row in payload["messages"])
        contents = " ".join(row["content"] for row in payload["messages"])
        assert probe._CONTENT in contents
        assert "Copy a supplied citation token verbatim" in contents
        refs = re.findall(r'"id":\s*"([^"]+)"', contents)
        assert refs
        assert "[HumanModel:" + refs[0] + "]" in contents
        seen.append(refs[0])
        return {"model": probe.MODEL, "done": True, "done_reason": "stop",
                "message": {"content":
                    "Simulated: I prioritize predictable evenings, not a "
                    "higher title. [HumanModel:" + refs[0] + "]"}}

    monkeypatch.setattr(probe, "_local_json", fake_local)
    result = probe.run_synthetic_e2e()
    assert result["status"] == "LIVE_SYNTHETIC_CITED_ANSWER"
    assert result["model_calls"] == 1
    assert result["private_owner_records_read"] == 0
    assert result["owner_answer_fidelity"] == "NOT_EVALUATED"
    assert result["answer_status"] == "SIMULATED_PROVISIONAL"
    assert result["cited_count"] == 1
    assert len(seen) == 1


def test_uncited_synthetic_reply_is_not_accepted(monkeypatch):
    monkeypatch.setattr(probe, "_local_json", lambda *a, **k: {
        "model": probe.MODEL, "done": True, "done_reason": "stop",
        "message": {"content": "I prefer a higher title."},
    })
    outcome = probe.run_synthetic_e2e()
    assert outcome["status"] == "NOT_ACCEPTED"
    assert outcome["reason"] == "MODEL_OUTPUT_NOT_EVIDENCE_BOUND"
    assert outcome["answer_status"] == "UNAVAILABLE"
    assert outcome["answer_reason"] == "OWNER_ANSWER_WITHOUT_SOURCE_CITATION"
    assert outcome["cited_count"] == 0
    assert outcome["model_calls"] == 1


def test_model_tool_request_is_rejected_before_delivery(monkeypatch):
    monkeypatch.setattr(probe, "_local_json", lambda *a, **k: {
        "model": probe.MODEL, "done": True, "done_reason": "stop",
        "message": {"content": "made-up answer",
                    "tool_calls": [{"function": {"name": "external_write"}}]},
    })
    result = probe.run_synthetic_e2e()
    assert result["status"] == "NOT_ACCEPTED"
    assert result["reason"] == "MODEL_ROUTE_UNAVAILABLE"
    assert result["answer_reason"] == "OWNER_SIMULATION_ROUTE_UNAVAILABLE"
    assert result["model_failure_code"] == "MODEL_RESPONSE_INVALID"
    assert result["model_attempts"] == 1


def test_real_model_timeout_reports_phase_without_prompt_or_error_text(monkeypatch):
    diag = {"phase": "ADMISSION", "model_state": "MODEL_NOT_CALLED",
            "model_calls": 0}
    def failed_local(path, payload=None, *, timeout=3):
        assert path == "/api/chat"
        raise TimeoutError("secret body: never export this")

    monkeypatch.setattr(probe, "_local_json", failed_local)
    result = probe.run_synthetic_e2e(diag)
    assert diag == {"phase": "MODEL_REQUEST", "model_state": "MODEL_TIMEOUT",
                    "model_calls": 1}
    assert result["status"] == "NOT_ACCEPTED"
    assert result["reason"] == "MODEL_ROUTE_UNAVAILABLE"
    assert result["answer_reason"] == "OWNER_SIMULATION_ROUTE_UNAVAILABLE"
    assert result["model_failure_code"] == "MODEL_TIMEOUT"
    assert result["model_failure_phase"] == "initial"
    assert result["model_attempts"] == 1
    assert "secret" not in repr(diag) + repr(result)


def test_unfinished_local_model_output_has_bounded_stage(monkeypatch):
    diag = {"phase": "ADMISSION", "model_state": "MODEL_NOT_CALLED",
            "model_calls": 0}
    monkeypatch.setattr(probe, "_local_json", lambda *a, **k: {
        "model": probe.MODEL, "done": True, "done_reason": "length",
        "message": {"content": "irrelevant secret-like sample"},
    })
    result = probe.run_synthetic_e2e(diag)
    assert result["reason"] == "MODEL_ROUTE_UNAVAILABLE"
    assert result["model_failure_code"] == "MODEL_RESPONSE_INVALID"
    assert diag["phase"] == "MODEL_REQUEST"
    assert diag["model_state"] == "MODEL_FINISH_LENGTH"
    assert diag["model_calls"] == 1


def test_valid_synthetic_reply_records_successful_stages(monkeypatch):
    diag = {"phase": "ADMISSION", "model_state": "MODEL_NOT_CALLED",
            "model_calls": 0}
    def fake_local(path, payload=None, *, timeout=3):
        import re
        text = " ".join(m["content"] for m in payload["messages"])
        ref = re.findall(r'"id":\s*"([^"]+)"', text)[0]
        return {"model": probe.MODEL, "done": True, "done_reason": "stop",
                "message": {"content":
                    "Simulated: predictable evenings [HumanModel:" + ref + "]"}}

    monkeypatch.setattr(probe, "_local_json", fake_local)
    result = probe.run_synthetic_e2e(diag)
    assert result["status"] == "LIVE_SYNTHETIC_CITED_ANSWER"
    assert diag == {"phase": "ANSWER_RETURNED", "model_state": "MODEL_REPLY_VALID",
                    "model_calls": 1}


def test_shared_chat_route_has_a_separate_exact_public_issue_contract():
    issue = {"number": 100, "title": probe.CHAT_TITLE, "body": probe.CHAT_BODY,
             "state": "open", "user": {"login": "quest7070-debug"}}
    event = {"action": "opened", "repository": {"full_name": probe.REPO},
             "issue": issue}
    assert probe.valid_owner_event(event, issue)
    assert not probe.valid_owner_event(event, {**issue, "body": probe.BODY})
    assert not probe.valid_owner_event({**event, "issue": {**issue, "body": []}}, issue)

def test_shared_chat_smoke_uses_fixed_adapter_and_never_publishes_reply(monkeypatch):
    from ai_foundation import shared_ollama9b_adapter
    class Execution:
        calls = 0
        def chat_payload(self, payload, model=None):
            assert model == "general" and payload["max_tokens"] == 256
            assert payload["messages"] == [{
                "role": "user", "content": "Reply with exactly " + probe._CHAT_REPLY
                    + " and nothing else."}]
            self.calls = 1
            return {"model": probe.MODEL, "choices": [{
                "finish_reason": "stop", "message": {
                    "role": "assistant", "content": probe._CHAT_REPLY}}]}
    monkeypatch.setattr(shared_ollama9b_adapter, "SharedOllama9BExecution", Execution)
    diagnosis = {}
    result = probe.run_shared_chat_route(diagnosis)
    assert result["status"] == "LIVE_SHARED_CHAT_ANSWER"
    assert result["model_calls"] == 1 and result["private_owner_records_read"] == 0
    assert probe._CHAT_REPLY not in repr(result) and "content" not in result

def test_bounded_cpu_settle_recovers_only_after_fresh_safe_admission():
    state = {"elapsed": 0, "calls": 0, "sleeps": []}
    def observe():
        state["calls"] += 1
        return ("BLOCKED_CPU_PRESSURE" if state["calls"] <= 2
                else "READY_SAFE_COLD_START_9B")
    def pause(delay):
        state["sleeps"].append(delay)
        state["elapsed"] += delay
    verdict = probe.wait_for_admission(
        observe=observe, monotonic=lambda: state["elapsed"], pause=pause)
    assert verdict == "READY_SAFE_COLD_START_9B"
    assert state["calls"] == 3
    assert state["sleeps"] == [15, 15]


def test_cpu_settle_stops_exactly_at_budget_without_model_call():
    state = {"elapsed": 0, "calls": 0}
    def observe():
        state["calls"] += 1
        return "BLOCKED_CPU_PRESSURE"
    def pause(delay):
        assert 0 < delay <= probe.CPU_SETTLE_POLL_SECONDS
        state["elapsed"] += delay
    verdict = probe.wait_for_admission(
        observe=observe, monotonic=lambda: state["elapsed"], pause=pause)
    assert verdict == "BLOCKED_CPU_PRESSURE"
    assert state["elapsed"] == probe.CPU_SETTLE_MAX_SECONDS
    assert state["calls"] == 1 + probe.CPU_SETTLE_MAX_SECONDS // probe.CPU_SETTLE_POLL_SECONDS


def test_cpu_settle_never_retries_unrelated_blocks():
    for other in ("BLOCKED_SHARED_OLLAMA_OTHER_MODEL",
                  "BLOCKED_COLD_START_MEMORY_HEADROOM",
                  "BLOCKED_LOCAL_INVENTORY_INVALID"):
        calls = []
        result = probe.wait_for_admission(
            observe=lambda: calls.append(other) or other,
            monotonic=lambda: 0, pause=lambda _: pytest.fail("no wait"))
        assert result == other
        assert calls == [other]

