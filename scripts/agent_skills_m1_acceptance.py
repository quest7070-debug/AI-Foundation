#!/usr/bin/env python3
"""Bounded no-credential, no-install M1 Agent Skills acceptance.

Runs only under the existing host_compute_lease.py wrapper in PR CI.
An exact already-resident 9B may be used. An unloaded but installed exact
9B may be used in this fixed one-shot PR acceptance ONLY after an additional
conservative CPU/RAM gate; normal host scheduling, other processes, models,
permissions, credentials, and production services remain unchanged. No
model is forcibly stopped, switched, installed, or evicted.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import time
from urllib import request
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_foundation.agent_skills import bundled_catalog
from ai_foundation.klm_9b_handler import MODEL, MODEL_DIGEST
from ai_foundation.klm_compute_admission import reclaimable_bytes, MAX_LOAD_PER_LOGICAL_CPU, MIN_RECLAIMABLE_BYTES

BASE = "http://127.0.0.1:11434"
_MAX_RESPONSE = 131072
_GIB = 1024 ** 3
# Reuse the existing KLM admission threshold on the same shared compute
# lease instead of inventing a higher, conflicting resource veto. A resource
# hint is not proof that a model will run without swapping.


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = request.build_opener(request.ProxyHandler({}), _NoRedirect())


def _local_json(path: str, payload: dict | None = None, *, timeout: int = 3) -> dict:
    if path not in {"/api/tags", "/api/ps", "/api/show", "/api/chat"}:
        raise ValueError("UNSUPPORTED_LOOPBACK_OPERATION")
    if path == "/api/show" and payload != {"model": MODEL}:
        raise ValueError("UNSUPPORTED_MODEL_SHOW_SCOPE")
    url = BASE + path
    data = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
    req = request.Request(url, data=data, method="POST" if data is not None else "GET",
                          headers={"Content-Type": "application/json"})
    with _OPENER.open(req, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError("LOCAL_HTTP_NON_200")
        raw = response.read(_MAX_RESPONSE + 1)
    if len(raw) > _MAX_RESPONSE:
        raise ValueError("LOCAL_REPLY_TOO_LARGE")
    row = json.loads(raw)
    if not isinstance(row, dict):
        raise ValueError("LOCAL_REPLY_NOT_OBJECT")
    return row


def _safe_http_category(exc: HTTPError) -> str:
    """Classify bounded localhost Ollama errors without logging raw model data.

    Only known fixed category identifiers leave this process. The error
    response may contain sensitive server details: never print or persist it.
    """
    code = getattr(exc, "code", None)
    if type(code) is not int or not 400 <= code <= 599:
        return "HTTP_UNKNOWN"
    try:
        raw = exc.read(4097)
        if len(raw) > 4096:
            return "HTTP_BODY_OVERSIZE"
        parsed = json.loads(raw)
        msg = parsed.get("error", "") if isinstance(parsed, dict) else ""
        msg = msg.lower() if type(msg) is str else ""
    except (ValueError, UnicodeError, OSError):
        msg = ""
    if code in (429, 503):
        return "SERVER_BUSY"
    if code in (404,):
        return "MODEL_NOT_FOUND"
    if any(word in msg for word in (
        "not enough memory", "requires more system memory",
        "insufficient memory", "out of memory", "cannot allocate memory"
    )):
        return "MODEL_MEMORY_REJECTED"
    if code == 400 and ("tool" in msg or "function" in msg):
        return "TOOL_SCHEMA_REJECTED"
    if code == 400 and ("think" in msg or "option" in msg):
        return "MODEL_OPTION_REJECTED"
    if code == 400:
        return "BAD_REQUEST_UNCLASSIFIED"
    if code >= 500:
        return "MODEL_SERVER_ERROR"
    return "HTTP_UNCLASSIFIED"


def _model_gate(tags: dict, ps: dict) -> str:
    available = tags.get("models")
    running = ps.get("models")
    if not isinstance(available, list) or not isinstance(running, list):
        return "BLOCKED_LOCAL_INVENTORY_INVALID"
    matching = [m for m in available if isinstance(m, dict)
                and m.get("name") == MODEL and m.get("digest") == MODEL_DIGEST]
    if not matching:
        return "BLOCKED_PINNED_9B_NOT_INSTALLED"
    loaded = [m for m in running if isinstance(m, dict)
              and (m.get("name") == MODEL or m.get("model") == MODEL)]
    if not loaded:
        return ("BLOCKED_SHARED_OLLAMA_OTHER_MODEL" if running
                else "BLOCKED_PINNED_9B_NOT_RESIDENT")
    if any(m.get("digest") != MODEL_DIGEST for m in loaded):
        return "BLOCKED_LOADED_MODEL_IDENTITY_MISMATCH"
    # An unrelated resident model must not be evicted or interrupted.
    if len(running) != 1:
        return "BLOCKED_SHARED_OLLAMA_OTHER_MODEL"
    return "READY_EXISTING_9B"


def _cold_start_gate(tags: dict, ps: dict) -> str:
    """One bounded CPU/vm_stat read under the *already held* shared host lease.

    Fail closed unless the exact installed model, no other resident model,
    the existing 9B reclaimable-memory minimum and low CPU pressure are
    observed. The installed size is validated, not treated as a second RAM gate. This cannot prove unmanaged Ollama clients
    idle, so it does not create any ongoing scheduling or eviction rights.
    """
    if _model_gate(tags, ps) != "BLOCKED_PINNED_9B_NOT_RESIDENT":
        return "BLOCKED_COLD_START_UNSAFE_STATE"
    target = next(m for m in tags["models"]
                  if isinstance(m, dict)
                  and m.get("name") == MODEL and m.get("digest") == MODEL_DIGEST)
    size = target.get("size")
    if type(size) is not int or not 0 < size < 16 * _GIB:
        return "BLOCKED_MODEL_SIZE_UNKNOWN"
    try:
        cpus = os.cpu_count()
        one_minute_load = os.getloadavg()[0]
        if (type(cpus) is not int or cpus < 1
                or not isinstance(one_minute_load, (float, int))
                or not 0 <= one_minute_load < 100000):
            return "BLOCKED_CPU_OBSERVATION_UNKNOWN"
        if one_minute_load >= cpus * MAX_LOAD_PER_LOGICAL_CPU:
            return "BLOCKED_CPU_PRESSURE"
        probe = subprocess.run(["/usr/bin/vm_stat"], capture_output=True,
                               text=True, timeout=3, check=False)
        if probe.returncode != 0:
            return "BLOCKED_MEMORY_UNKNOWN"
        available = reclaimable_bytes(probe.stdout)
        if available is None:
            return "BLOCKED_MEMORY_UNKNOWN"
        if available < MIN_RECLAIMABLE_BYTES:
            return "BLOCKED_COLD_START_MEMORY_HEADROOM"
        return "READY_SAFE_COLD_START_9B"
    except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired):
        return "BLOCKED_RESOURCE_PROBE_UNKNOWN"


def _ollama_messages(messages, instructions: str = "") -> list[dict]:
    """Map the existing Agent history to Ollama's native /api/chat schema.

    The generic Foundation serializer uses the OpenAI representation where
    function.arguments is a JSON *string*. Ollama native /api/chat instead
    expects an argument *object* and tool result messages without OpenAI's
    tool_call_id field. Preserve Pydantic Agent history and exact host tools;
    only convert the wire representation, never synthesize a model tool call.
    """
    from ai_foundation.routed_agent_model import _messages
    result = _messages(messages, instructions)
    call_names = {}
    for row in result:
        if row.get("role") == "assistant":
            calls = row.get("tool_calls", ())
            converted = []
            for call in calls:
                if not isinstance(call, dict):
                    raise ValueError("INVALID_OLLAMA_TOOL_CALL")
                fn = call.get("function", {})
                if not isinstance(fn, dict) or type(fn.get("name")) is not str:
                    raise ValueError("INVALID_OLLAMA_TOOL_NAME")
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (ValueError, TypeError) as exc:
                        raise ValueError("INVALID_OLLAMA_TOOL_ARGUMENTS") from exc
                if not isinstance(args, dict):
                    raise ValueError("INVALID_OLLAMA_TOOL_ARGUMENTS")
                call_id = call.get("id")
                if type(call_id) is not str or not call_id or call_id in call_names:
                    raise ValueError("INVALID_OLLAMA_TOOL_CALL_ID")
                call_names[call_id] = fn["name"]
                converted.append({"function": {"name": fn["name"],
                                                "arguments": args}})
            if converted:
                row["tool_calls"] = converted
                row["content"] = row.get("content") or ""
        elif row.get("role") == "tool":
            call_id = row.pop("tool_call_id", None)
            name = call_names.get(call_id)
            if not name:
                raise ValueError("UNMATCHED_OLLAMA_TOOL_RESULT")
            row["tool_name"] = name
        if not isinstance(row.get("content"), str):
            raise ValueError("INVALID_OLLAMA_MESSAGE_CONTENT")
    return result


def _verify_public_data_receipt(data: str) -> str:
    """Strictly verify the deterministic DATA result, never a model claim.

    Return only an allowlisted cause code, not the raw result or its values.
    This also detects wrong model-supplied arguments without relaxing scoring.
    """
    import ast
    if type(data) is not str or not 0 < len(data) <= 2048:
        return "DATA_RESULT_MISSING_OR_OVERSIZE"
    try:
        report = ast.literal_eval(data)
    except (ValueError, SyntaxError, TypeError, RecursionError):
        return "DATA_RESULT_INVALID"
    if type(report) is not dict:
        return "DATA_RESULT_NOT_OBJECT"
    if report.get("type") != "array":
        return "DATA_INPUT_NOT_ARRAY"
    keys = ("count", "numeric_count", "min", "max", "mean")
    if any(type(report.get(key)) not in (int, float) for key in keys):
        return "DATA_FIELDS_MISSING_OR_INVALID"
    if (report["count"], report["numeric_count"], report["min"],
            report["max"], report["mean"]) != (3, 3, 3.0, 11.0, 7.0):
        return "DATA_VALUES_MISMATCH"
    return "VERIFIED"


def _exercise(skills):
    """A/B: identical public fixture and existing DATA tool; only skill differs."""
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart
    from pydantic_ai.models.function import FunctionModel
    from ai_foundation.auto_agent import AutoCapabilityAgent
    from ai_foundation.capability_request import CapabilityRequest
    from ai_foundation.capability_execution import CapabilityExecutor
    from ai_foundation.core import GuardState
    from ai_foundation.guard import GuardCore

    state = GuardState()
    counts = {"model_calls": 0, "output_tokens": 0, "input_tokens": 0}
    class Observer(CapabilityExecutor):
        def __init__(self):
            super().__init__(inference=None, guard=GuardCore(state))
            self.capabilities = []
            self.data_result = None
        def execute(self, req, text, run):
            self.capabilities.append(req.capability)
            out = super().execute(req, text, run)
            if req.capability == "DATA":
                self.data_result = out
            return out
    executor = Observer()
    touched = []
    catalog = bundled_catalog(ROOT) if skills else None
    if skills:
        if catalog is None:
            raise RuntimeError("MISSING_TRUSTED_SKILL_BUNDLE")
        original_load = catalog.load
        def traced_load(name):
            touched.append(name)
            return original_load(name)
        catalog.load = traced_load

    def model(messages, info):
        tools = [{"type": "function", "function": {
            "name": item.name,
            "description": item.description or "",
            "parameters": item.parameters_json_schema,
        }} for item in info.function_tools]
        payload = {
            "model": MODEL,
            "messages": _ollama_messages(messages, getattr(info, "instructions", "") or ""),
            "tools": tools,
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "num_predict": 192, "num_ctx": 4096},
        }
        row = _local_json("/api/chat", payload, timeout=105)
        if row.get("model") != MODEL or row.get("done") is not True:
            raise ValueError("INCOMPLETE_OR_WRONG_MODEL_REPLY")
        msg = row.get("message", {})
        if not isinstance(msg, dict):
            raise ValueError("INVALID_MODEL_MESSAGE")
        parts = []
        if isinstance(msg.get("content"), str) and msg["content"]:
            parts.append(TextPart(msg["content"][:4096]))
        calls = msg.get("tool_calls") or []
        if len(calls) > 2:
            raise ValueError("EXCESS_MODEL_TOOL_CALLS")
        for index, call in enumerate(calls):
            fn = call.get("function", {})
            if not isinstance(fn, dict) or not isinstance(fn.get("name"), str):
                raise ValueError("INVALID_TOOL_CALL")
            args = fn.get("arguments", {})
            if not isinstance(args, dict):
                raise ValueError("INVALID_TOOL_ARGUMENTS")
            parts.append(ToolCallPart(fn["name"], json.dumps(args),
                                      tool_call_id="live_%d_%d" % (counts["model_calls"], index)))
        if not parts:
            raise ValueError("EMPTY_MODEL_REPLY")
        counts["model_calls"] += 1
        counts["output_tokens"] += int(row.get("eval_count", 0) or 0)
        counts["input_tokens"] += int(row.get("prompt_eval_count", 0) or 0)
        return ModelResponse(parts=parts, model_name=MODEL)

    agent = AutoCapabilityAgent(
        FunctionModel(model), executor,
        CapabilityRequest("CHAT", owner_id="public-fixture",
                          data_operation="json_summary",
                          data_value_contract="numeric_array"),
        skill_catalog=catalog,
    )
    prompt = (
        "Calculate a verified summary of this public JSON array [3,7,11]. "
        "Use the available bounded data tool rather than mental arithmetic. "
        "Return count, minimum, maximum, and mean. "
        'Call the DATA tool with the exact JSON arguments {"value":[3,7,11]}. '
        "The value argument is the numeric array itself, NEVER a nested "
        "object or a string. "
        "This request requires evidence verification. If load_skill is among "
        "the available tools, first load one relevant host-pinned reference "
        "using its EXACT listed name, then use DATA. "
        "If load_skill is unavailable, use DATA directly."
    )
    start = time.monotonic()
    out = agent.run(prompt)
    duration = round(time.monotonic() - start, 3)
    # Validate the independent deterministic DATA tool receipt, not the model's
    # claim that it used a tool. No final text or raw context goes to CI logs.
    data = executor.data_result or ""
    data_status = _verify_public_data_receipt(data)
    selected_skills = [x for x in touched
                       if x in ("evidence-brief", "verified-artifact")]
    # Both are relevant first-party pinned procedures; development-handoff is
    # not. The model must actually call load_skill to count as a success.
    relevant_skill_loaded = (bool(touched) and touched == selected_skills
                             and len(set(touched)) == len(touched))
    return {
        "skill_loaded": relevant_skill_loaded if skills else not touched,
        "loaded_skills": selected_skills,
        "data_called": executor.capabilities == ["DATA"],
        "data_receipt_verified": data_status == "VERIFIED",
        "data_receipt_status": data_status,
        "final_nonempty": bool(str(out).strip()),
        "model_calls": counts["model_calls"],
        "input_tokens": counts["input_tokens"],
        "output_tokens": counts["output_tokens"],
        "elapsed_seconds": duration,
        "no_guard_effects": not bool(state.effects),
    }


def _readback_receipt(receipt: dict) -> None:
    # A fresh per-run temporary file, with independent bytes read back before
    # displaying bounded metadata. No private input, credentials or raw output.
    root = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())).resolve()
    with tempfile.NamedTemporaryFile(dir=root, prefix="skills-receipt-",
                                     suffix=".json", delete=False) as file:
        destination = Path(file.name)
        raw = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
        file.write(raw)
    try:
        observed = destination.read_bytes()
        if hashlib.sha256(observed).digest() != hashlib.sha256(raw).digest():
            raise RuntimeError("RECEIPT_INDEPENDENT_READBACK_MISMATCH")
        if json.loads(observed) != receipt:
            raise RuntimeError("RECEIPT_PARSE_MISMATCH")
        print("AGENT_SKILLS_M1_RECEIPT=" + json.dumps({
            **receipt, "receipt_sha256": hashlib.sha256(observed).hexdigest(),
            "readback_verified": True,
        }, sort_keys=True, separators=(",", ":")), flush=True)
    finally:
        destination.unlink(missing_ok=True)


def main() -> int:
    catalog = bundled_catalog(ROOT)
    if catalog is None:
        raise RuntimeError("BUNDLED_CATALOG_MISSING")
    # Re-hash every bundled SKILL.md from current checkout; no new loading.
    for row in catalog.summaries():
        catalog.load(row.name)
    result = {
        "schema": 1,
        "git_sha": os.environ.get("GITHUB_SHA", "UNKNOWN"),
        "skill_catalog": "PINNED_READBACK_PASS",
        "test_fixture": "public-json-[3,7,11]",
        "model": MODEL,
        "model_digest_verified": False,
        "status": "BLOCKED_PRECHECK",
    }
    try:
        tags = _local_json("/api/tags")
        ps = _local_json("/api/ps")
        gate = _model_gate(tags, ps)
    except Exception as exc:
        gate = "BLOCKED_LOCAL_PROBE_" + type(exc).__name__
    # Explicit opt-in is confined to this one fixed PR acceptance step.
    # Never load a model merely because CI, an operator poll, or a skill exists.
    if (gate == "BLOCKED_PINNED_9B_NOT_RESIDENT"
            and os.environ.get("AGENT_SKILLS_ONE_SHOT_COLD_START") == "1"):
        gate = _cold_start_gate(tags, ps)
    result["preflight"] = gate
    result["model_digest_verified"] = gate == "READY_EXISTING_9B"
    if gate not in {"READY_EXISTING_9B", "READY_SAFE_COLD_START_9B"}:
        result["status"] = gate
        _readback_receipt(result)
        return 0
    # This is a cheap, read-only model metadata check. Never trust a skill
    # or prompt to select the model name for /api/show.
    try:
        metadata = _local_json("/api/show", {"model": MODEL}, timeout=4)
        capabilities = metadata.get("capabilities")
        if isinstance(capabilities, list) and all(type(x) is str for x in capabilities):
            result["tool_capability"] = "SUPPORTED" if "tools" in capabilities else "UNSUPPORTED"
        else:
            result["tool_capability"] = "UNKNOWN"
    except (OSError, ValueError, RuntimeError, HTTPError) as probe_error:
        result["tool_capability"] = "UNKNOWN_" + type(probe_error).__name__
    if result["tool_capability"] == "UNSUPPORTED":
        result["status"] = "BLOCKED_PINNED_MODEL_NO_TOOL_CAPABILITY"
        _readback_receipt(result)
        return 0
    try:
        baseline = _exercise(False)
        with_skills = _exercise(True)
        # Check exact model identity AFTER every real E2E, even if the 9B
        # was already resident at preflight. An external client may switch
        # Ollama during a long task; a stale initial digest cannot prove it.
        final_gate = _model_gate(_local_json("/api/tags"),
                                 _local_json("/api/ps"))
        result["model_digest_verified"] = final_gate == "READY_EXISTING_9B"
        result["postflight"] = final_gate
        result["baseline"] = baseline
        result["with_skills"] = with_skills
        ok = all((baseline["data_called"], baseline["data_receipt_verified"],
                  baseline["no_guard_effects"], with_skills["skill_loaded"],
                  with_skills["data_called"], with_skills["data_receipt_verified"],
                  with_skills["no_guard_effects"], with_skills["final_nonempty"],
                  result["model_digest_verified"]))
        result["status"] = "REAL_MODEL_SKILL_E2E_PASS" if ok else "REAL_MODEL_SKILL_E2E_FAIL"
    except Exception as exc:
        result["status"] = "REAL_MODEL_SKILL_E2E_ERROR"
        result["error_class"] = type(exc).__name__
        # Export only bounded categories and a status, never the response
        # body, server message, prompt, tool result or runtime logs.
        if isinstance(exc, HTTPError) and type(exc.code) is int:
            if 400 <= exc.code <= 599:
                result["http_status"] = exc.code
                result["http_category"] = _safe_http_category(exc)
                if result["http_category"] in ("MODEL_MEMORY_REJECTED", "SERVER_BUSY"):
                    result["status"] = "BLOCKED_OLLAMA_" + result["http_category"]
    _readback_receipt(result)
    return 0 if (result["status"] == "REAL_MODEL_SKILL_E2E_PASS"
                 or result["status"].startswith("BLOCKED_OLLAMA_")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
