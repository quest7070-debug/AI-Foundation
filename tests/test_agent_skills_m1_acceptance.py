"""No-network safety and receipt tests for the bounded real-M1 acceptance probe."""
from __future__ import annotations
import json
import os
from pathlib import Path
import pytest

from scripts import agent_skills_m1_acceptance as probe


def test_only_identical_installed_and_resident_9b_is_eligible():
    tag = {"models": [{"name": probe.MODEL, "digest": probe.MODEL_DIGEST}]}
    active = {"models": [{"name": probe.MODEL, "digest": probe.MODEL_DIGEST}]}
    assert probe._model_gate(tag, active) == "READY_EXISTING_9B"
    assert probe._model_gate(tag, {"models": []}) == "BLOCKED_PINNED_9B_NOT_RESIDENT"
    assert probe._model_gate({"models": []}, active) == "BLOCKED_PINNED_9B_NOT_INSTALLED"
    assert probe._model_gate(tag, {"models": [{"name": probe.MODEL, "digest": "mismatch"}]}) == "BLOCKED_LOADED_MODEL_IDENTITY_MISMATCH"
    assert probe._model_gate(tag, {"models": active["models"] + [{"name": "other", "digest": "x"}]}) == "BLOCKED_SHARED_OLLAMA_OTHER_MODEL"
    assert probe._model_gate({}, active) == "BLOCKED_LOCAL_INVENTORY_INVALID"


def test_local_transport_allows_only_fixed_loopback_api_paths():
    with pytest.raises(ValueError, match="UNSUPPORTED_LOOPBACK_OPERATION"):
        probe._local_json("https://example.invalid", {})
    with pytest.raises(ValueError, match="UNSUPPORTED_LOOPBACK_OPERATION"):
        probe._local_json("/api/pull", {"model": probe.MODEL})
    with pytest.raises(ValueError, match="UNSUPPORTED_LOOPBACK_OPERATION"):
        probe._local_json("/api/delete", {"model": probe.MODEL})


def test_receipt_is_independently_written_and_read_back(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    source = {"schema": 1, "status": "BLOCKED_PINNED_9B_NOT_RESIDENT",
              "skill_catalog": "PINNED_READBACK_PASS"}
    probe._readback_receipt(source)
    output = capsys.readouterr().out.strip()
    assert output.startswith("AGENT_SKILLS_M1_RECEIPT=")
    payload = json.loads(output.split("=", 1)[1])
    assert payload["status"] == source["status"]
    assert payload["readback_verified"] is True
    assert len(payload["receipt_sha256"]) == 64
    assert not list(tmp_path.glob("skills-receipt-*"))


def test_preflight_skips_model_when_not_running(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    calls = []
    monkeypatch.setattr(probe, "_local_json",
                        lambda path, payload=None, **kw: calls.append(path) or
                        {"models": []})
    monkeypatch.setattr(probe, "_exercise",
                        lambda *_: pytest.fail("must not call model on blocked preflight"))
    assert probe.main() == 0
    result = json.loads(capsys.readouterr().out.strip().split("=", 1)[1])
    assert result["status"] == "BLOCKED_PINNED_9B_NOT_INSTALLED"
    assert result["skill_catalog"] == "PINNED_READBACK_PASS"
    assert calls == ["/api/tags", "/api/ps"]


def _installed(size=5 * 1024**3):
    return {"models": [{"name": probe.MODEL, "digest": probe.MODEL_DIGEST, "size": size}]}


def _vm_stat_pages(total_pages: int) -> str:
    # macOS vm_stat's 16 KiB pages, never count purgeable twice.
    return ("Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
            f"Pages free: {total_pages // 2}.\n"
            f"Pages inactive: {total_pages - total_pages // 2}.\n"
            "Pages speculative: 0.\n")


def test_cold_start_gate_uses_exact_model_size_and_one_resource_sample(monkeypatch):
    from subprocess import CompletedProcess
    calls = []
    def vm(argv, **kwargs):
        calls.append((argv, kwargs))
        return CompletedProcess(argv, 0, _vm_stat_pages(550000), "")
    monkeypatch.setattr(probe.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(probe.os, "getloadavg", lambda: (1., 1., 1.))
    monkeypatch.setattr(probe.subprocess, "run", vm)
    assert probe._cold_start_gate(_installed(), {"models": []}) == "READY_SAFE_COLD_START_9B"
    assert len(calls) == 1 and calls[0][0] == ["/usr/bin/vm_stat"]
    assert calls[0][1]["timeout"] == 3


def test_cold_start_gate_fails_closed_on_low_memory_and_different_resident(monkeypatch):
    from subprocess import CompletedProcess
    calls = []
    monkeypatch.setattr(probe.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(probe.os, "getloadavg", lambda: (1., 1., 1.))
    monkeypatch.setattr(probe.subprocess, "run", lambda argv, **kw:
                        calls.append(argv) or CompletedProcess(
                            argv, 0, _vm_stat_pages(200000), ""))
    assert probe._cold_start_gate(_installed(), {"models": []}) == "BLOCKED_COLD_START_MEMORY_HEADROOM"
    assert probe._cold_start_gate(_installed(), {"models": [{"name": "other"}]}) == "BLOCKED_COLD_START_UNSAFE_STATE"
    assert len(calls) == 1


@pytest.mark.parametrize("size", [None, 0, -1, "5000000", 17*1024**3, True])
def test_cold_start_gate_rejects_ambiguous_model_size_before_memory_probe(monkeypatch, size):
    monkeypatch.setattr(probe.subprocess, "run",
                        lambda *a, **kw: pytest.fail("no vm_stat for bad size"))
    assert probe._cold_start_gate(_installed(size), {"models": []}) == "BLOCKED_MODEL_SIZE_UNKNOWN"


def test_cold_start_gate_defers_cpu_pressure_without_memory_probe(monkeypatch):
    monkeypatch.setattr(probe.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(probe.os, "getloadavg", lambda: (7.0, 6., 6.))
    monkeypatch.setattr(probe.subprocess, "run",
                        lambda *a, **kw: pytest.fail("CPU gate must run first"))
    assert probe._cold_start_gate(_installed(), {"models": []}) == "BLOCKED_CPU_PRESSURE"


def test_cold_start_unknown_cpu_never_samples_ram(monkeypatch):
    monkeypatch.setattr(probe.os, "cpu_count", lambda: None)
    monkeypatch.setattr(probe.os, "getloadavg", lambda: (1., 1., 1.))
    monkeypatch.setattr(probe.subprocess, "run",
                        lambda *a, **kw: pytest.fail("unknown CPU must stop"))
    assert probe._cold_start_gate(_installed(), {"models": []}) == "BLOCKED_CPU_OBSERVATION_UNKNOWN"


def test_cold_start_needs_explicit_one_shot_opt_in_and_reports_blocked(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.delenv("AGENT_SKILLS_ONE_SHOT_COLD_START", raising=False)
    calls = []
    def transport(path, payload=None, **kwargs):
        calls.append(path)
        return _installed() if path == "/api/tags" else {"models": []}
    monkeypatch.setattr(probe, "_local_json", transport)
    monkeypatch.setattr(probe, "_cold_start_gate",
                        lambda *a: pytest.fail("cold start must be off by default"))
    monkeypatch.setattr(probe, "_exercise",
                        lambda *a: pytest.fail("blocked gate must not infer"))
    assert probe.main() == 0
    assert calls == ["/api/tags", "/api/ps"]
    assert json.loads(capsys.readouterr().out.split("=",1)[1])["status"] == "BLOCKED_PINNED_9B_NOT_RESIDENT"


def test_cold_start_low_headroom_is_recoverable_block_without_inference(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("AGENT_SKILLS_ONE_SHOT_COLD_START", "1")
    monkeypatch.setattr(probe, "_local_json", lambda path, payload=None, **kw:
                        _installed() if path == "/api/tags" else {"models": []})
    monkeypatch.setattr(probe, "_cold_start_gate",
                        lambda *args: "BLOCKED_COLD_START_MEMORY_HEADROOM")
    monkeypatch.setattr(probe, "_exercise", lambda *args: pytest.fail("no model call on low RAM"))
    assert probe.main() == 0
    result = json.loads(capsys.readouterr().out.split("=", 1)[1])
    assert result["status"] == "BLOCKED_COLD_START_MEMORY_HEADROOM"
    assert result["model_digest_verified"] is False
    assert result["readback_verified"] is True


def test_cold_start_needs_digest_readback_after_synthetic_e2e(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("AGENT_SKILLS_ONE_SHOT_COLD_START", "1")
    observations = {"ps": 0, "attempts": []}
    def transport(path, payload=None, **kwargs):
        if path == "/api/tags":
            return _installed()
        observations["ps"] += 1
        if observations["ps"] == 1:
            return {"models": []}
        return {"models": [{"name": probe.MODEL, "digest": probe.MODEL_DIGEST}]}
    monkeypatch.setattr(probe, "_local_json", transport)
    monkeypatch.setattr(probe, "_cold_start_gate", lambda *args: "READY_SAFE_COLD_START_9B")
    def exercise(skills):
        observations["attempts"].append(skills)
        return {
            "skill_loaded": bool(skills),
            "data_called": True,
            "data_receipt_verified": True,
            "no_guard_effects": True,
            "final_nonempty": True,
        }
    monkeypatch.setattr(probe, "_exercise", exercise)
    assert probe.main() == 0
    result = json.loads(capsys.readouterr().out.split("=", 1)[1])
    assert result["status"] == "REAL_MODEL_SKILL_E2E_PASS"
    assert result["model_digest_verified"] is True
    assert observations["attempts"] == [False, True]
    assert result["readback_verified"] is True


def test_cold_start_refuses_wrong_digest_even_if_tool_calls_look_good(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("AGENT_SKILLS_ONE_SHOT_COLD_START", "1")
    counts = {"ps": 0}
    def transport(path, payload=None, **kw):
        if path == "/api/tags":
            return _installed()
        counts["ps"] += 1
        return {"models": []} if counts["ps"] == 1 else {
            "models": [{"name": probe.MODEL, "digest": "wrong"}]}
    monkeypatch.setattr(probe, "_local_json", transport)
    monkeypatch.setattr(probe, "_cold_start_gate", lambda *a: "READY_SAFE_COLD_START_9B")
    monkeypatch.setattr(probe, "_exercise", lambda skills: {
        "skill_loaded": skills, "data_called": True,
        "data_receipt_verified": True, "no_guard_effects": True,
        "final_nonempty": True})
    assert probe.main() == 1
    result = json.loads(capsys.readouterr().out.split("=", 1)[1])
    assert result["status"] == "REAL_MODEL_SKILL_E2E_FAIL"
    assert result["postflight"] == "BLOCKED_LOADED_MODEL_IDENTITY_MISMATCH"



def test_reuses_existing_km_9b_minimum_without_extra_cold_start_memory_veto(monkeypatch):
    from subprocess import CompletedProcess
    from ai_foundation.klm_compute_admission import MIN_RECLAIMABLE_BYTES
    assert MIN_RECLAIMABLE_BYTES == 4 * 1024 ** 3
    monkeypatch.setattr(probe.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(probe.os, "getloadavg", lambda: (1., 1., 1.))
    # 5 GiB satisfies the canonical existing leased 9B admission; do not
    # require a made-up size+2GiB second gate in acceptance.
    monkeypatch.setattr(probe.subprocess, "run", lambda argv, **kw:
                        CompletedProcess(argv, 0, _vm_stat_pages(327680), ""))
    assert probe._cold_start_gate(_installed(), {"models": []}) == "READY_SAFE_COLD_START_9B"



def test_live_http_error_exports_status_only_never_raw_ollama_payload(monkeypatch, tmp_path, capsys):
    from urllib.error import HTTPError
    import io
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.delenv("AGENT_SKILLS_ONE_SHOT_COLD_START", raising=False)
    def local(path, payload=None, **kwargs):
        if path == "/api/tags":
            return _installed()
        return {"models": [{"name": probe.MODEL, "digest": probe.MODEL_DIGEST}]}
    monkeypatch.setattr(probe, "_local_json", local)
    def denied(*args):
        raise HTTPError("http://127.0.0.1:11434/api/chat", 400,
                        "SECRET_RAW_SERVER_DETAIL", None,
                        io.BytesIO(b"SECRET_SERVER_BODY"))
    monkeypatch.setattr(probe, "_exercise", denied)
    assert probe.main() == 1
    printed = capsys.readouterr().out
    result = json.loads(printed.strip().split("=", 1)[1])
    assert result["status"] == "REAL_MODEL_SKILL_E2E_ERROR"
    assert result["error_class"] == "HTTPError"
    assert result["http_status"] == 400
    assert result["readback_verified"] is True
    assert "SECRET_RAW_SERVER_DETAIL" not in printed
    assert "SECRET_SERVER_BODY" not in printed



@pytest.mark.parametrize("status,error,expected", [
    (400, "tools: invalid function parameters", "TOOL_SCHEMA_REJECTED"),
    (400, "invalid think option", "MODEL_OPTION_REJECTED"),
    (400, "bad request", "BAD_REQUEST_UNCLASSIFIED"),
    (404, "model not found", "MODEL_NOT_FOUND"),
    (500, "model requires more system memory", "MODEL_MEMORY_REJECTED"),
    (500, "the model failed to generate a response", "MODEL_SERVER_ERROR"),
    (503, "server busy", "SERVER_BUSY"),
])
def test_safe_http_error_classification_never_echoes_raw_body(status, error, expected):
    from urllib.error import HTTPError
    import io
    exc = HTTPError("http://127.0.0.1:11434/api/chat", status,
                    "UNTRUSTED_HEADER_SECRET", None,
                    io.BytesIO(json.dumps({"error": error, "secret": "SECRET"}).encode()))
    assert probe._safe_http_category(exc) == expected


def test_fixed_model_show_scope_only():
    with pytest.raises(ValueError, match="UNSUPPORTED_MODEL_SHOW_SCOPE"):
        probe._local_json("/api/show", {"model": "unreviewed:latest"})


def test_unsupported_show_tools_never_attempts_model(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.delenv("AGENT_SKILLS_ONE_SHOT_COLD_START", raising=False)
    def local(path, payload=None, **kwargs):
        if path == "/api/tags":
            return _installed()
        if path == "/api/ps":
            return {"models": [{"name": probe.MODEL, "digest": probe.MODEL_DIGEST}]}
        if path == "/api/show":
            assert payload == {"model": probe.MODEL}
            return {"capabilities": ["completion", "vision"]}
        pytest.fail("unexpected endpoint")
    monkeypatch.setattr(probe, "_local_json", local)
    monkeypatch.setattr(probe, "_exercise", lambda *_: pytest.fail("unsupported tools cannot infer"))
    assert probe.main() == 0
    result = json.loads(capsys.readouterr().out.split("=", 1)[1])
    assert result["status"] == "BLOCKED_PINNED_MODEL_NO_TOOL_CAPABILITY"
    assert result["tool_capability"] == "UNSUPPORTED"


def test_safe_model_memory_error_reports_block_not_model_pass(monkeypatch, tmp_path, capsys):
    from urllib.error import HTTPError
    import io
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.delenv("AGENT_SKILLS_ONE_SHOT_COLD_START", raising=False)
    def local(path, payload=None, **kwargs):
        if path == "/api/tags":
            return _installed()
        if path == "/api/ps":
            return {"models": [{"name": probe.MODEL, "digest": probe.MODEL_DIGEST}]}
        return {"capabilities": ["tools"]}
    monkeypatch.setattr(probe, "_local_json", local)
    monkeypatch.setattr(probe, "_exercise", lambda *_: (_ for _ in ()).throw(
        HTTPError("http://127.0.0.1:11434/api/chat", 500, "SECRET_REASON", None,
                  io.BytesIO(b'{"error":"model requires more system memory than is available"}'))
    ))
    assert probe.main() == 0
    printed = capsys.readouterr().out
    result = json.loads(printed.split("=", 1)[1])
    assert result["status"] == "BLOCKED_OLLAMA_MODEL_MEMORY_REJECTED"
    assert result["http_status"] == 500
    assert result["http_category"] == "MODEL_MEMORY_REJECTED"
    assert result["model_digest_verified"] is True
    assert "SECRET_REASON" not in printed



def test_pydantic_tool_history_serializes_to_exact_ollama_native_schema():
    from pydantic_ai.messages import (
        ModelRequest, ModelResponse, UserPromptPart, ToolCallPart, ToolReturnPart,
    )
    history = [
        ModelRequest(parts=[UserPromptPart("Compute public array [3,7,11].")]),
        ModelResponse(parts=[
            ToolCallPart("data", {"value": [3, 7, 11]}, tool_call_id="call_1")
        ]),
        ModelRequest(parts=[
            ToolReturnPart("data", "{'count': 3, 'mean': 7.0}", tool_call_id="call_1")
        ]),
    ]
    rows = probe._ollama_messages(history, "Trusted host instructions.")
    assert rows[0] == {"role": "system", "content": "Trusted host instructions."}
    assert rows[1]["role"] == "user"
    assert rows[2] == {
        "role": "assistant", "content": "",
        "tool_calls": [{"function": {
            "name": "data", "arguments": {"value": [3, 7, 11]}
        }}],
    }
    assert rows[3] == {"role": "tool", "tool_name": "data",
                       "content": "{'count': 3, 'mean': 7.0}"}
    assert "tool_call_id" not in json.dumps(rows)
    assert '"arguments": "{' not in json.dumps(rows)


def test_malformed_openai_tool_arguments_fail_before_ollama_request(monkeypatch):
    # Pydantic may normalize tool args before serialization. Inject a genuinely
    # invalid wire representation at the serializer boundary instead.
    from ai_foundation import routed_agent_model
    monkeypatch.setattr(routed_agent_model, "_messages", lambda *_: [
        {"role": "assistant", "content": None, "tool_calls": [{
            "type": "function",
            "function": {"name": "data", "arguments": '{"value": invalid}'},
        }]}
    ])
    with pytest.raises(ValueError, match="INVALID_OLLAMA_TOOL_ARGUMENTS"):
        probe._ollama_messages([])



def test_already_resident_9b_also_requires_postflight_digest_readback(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.delenv("AGENT_SKILLS_ONE_SHOT_COLD_START", raising=False)
    observation = {"ps": 0, "model_paths": []}
    def local(path, payload=None, **kw):
        observation["model_paths"].append(path)
        if path == "/api/tags":
            return _installed()
        if path == "/api/show":
            return {"capabilities": ["tools"]}
        observation["ps"] += 1
        if observation["ps"] == 1:
            return {"models": [{"name": probe.MODEL, "digest": probe.MODEL_DIGEST}]}
        return {"models": [{"name": probe.MODEL, "digest": "other"}]}
    monkeypatch.setattr(probe, "_local_json", local)
    monkeypatch.setattr(probe, "_exercise", lambda enabled: {
        "skill_loaded": bool(enabled),
        "data_called": True,
        "data_receipt_verified": True,
        "no_guard_effects": True,
        "final_nonempty": True,
    })
    assert probe.main() == 1
    result = json.loads(capsys.readouterr().out.split("=", 1)[1])
    assert result["status"] == "REAL_MODEL_SKILL_E2E_FAIL"
    assert result["postflight"] == "BLOCKED_LOADED_MODEL_IDENTITY_MISMATCH"
    assert result["model_digest_verified"] is False
    assert observation["model_paths"].count("/api/ps") == 2



def test_model_tool_result_id_must_match_a_preceding_tool_call():
    from pydantic_ai.messages import ModelRequest, ToolReturnPart
    with pytest.raises(ValueError, match="UNMATCHED_OLLAMA_TOOL_RESULT"):
        probe._ollama_messages([
            ModelRequest(parts=[
                ToolReturnPart("data", "verified", tool_call_id="unmatched")
            ])
        ])


@pytest.mark.parametrize("receipt,expected", [
    ("{'type': 'array', 'count': 3, 'numeric_count': 3, 'min': 3.0, 'max': 11.0, 'mean': 7.0}", "VERIFIED"),
    ("{'type': 'array', 'count': 3, 'numeric_count': 3, 'min': 3, 'max': 11, 'mean': 7}", "VERIFIED"),
    ("{'type': 'object', 'count': 1, 'keys': ['value']}", "DATA_INPUT_NOT_ARRAY"),
    ("{'type': 'array', 'count': 3, 'numeric_count': 3, 'min': 3, 'max': 11, 'mean': 8}", "DATA_VALUES_MISMATCH"),
    ("{'count': 3}", "DATA_INPUT_NOT_ARRAY"),
    ("garbled response", "DATA_RESULT_INVALID"),
    ("", "DATA_RESULT_MISSING_OR_OVERSIZE"),
    ("{'type': 'array', 'count': True, 'numeric_count': 3, 'min': 3, 'max': 11, 'mean': 7}", "DATA_FIELDS_MISSING_OR_INVALID"),
])
def test_structured_data_receipt_requires_exact_public_values(receipt, expected):
    assert probe._verify_public_data_receipt(receipt) == expected
