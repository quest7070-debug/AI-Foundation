#!/usr/bin/env python3
"""Owner-only M1 one-shot: synthetic HumanModel source -> real pinned local 9B -> cited answer.

Never read real HumanModel files, owner identity, chat text, secrets or production
Guard. The disposable SQLite source tests the real evidence adapter/agent chain.
Only allowlisted status is posted to the authenticated owner's GitHub Issue.
"""
from __future__ import annotations

import json
import os
from functools import partial
from pathlib import Path
import re
import sys
import time
from tempfile import TemporaryDirectory
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for p in ("src", "scripts", "experiments/human_model"):
    sys.path.insert(0, str(ROOT / p))

import m1_development_bridge as bridge
from agent_skills_m1_acceptance import (
    MODEL, MODEL_DIGEST, _cold_start_gate, _local_json, _model_gate,
)

REPO = "quest7070-dev/AI-Foundation"
WORKFLOW = "Foundation M1 HumanModel synthetic 9B E2E"
TITLE = "Foundation HumanModel 9B E2E: synthetic owner answer"
BODY = "<!-- foundation-humanmodel-9b-e2e: synthetic-only-v1 -->"
CHAT_TITLE = "Foundation Local 9B E2E: shared chat route"
CHAT_BODY = "<!-- foundation-local9b-shared-chat-e2e: fixed-public-v1 -->"
_CHAT_REPLY = "FOUNDATION_SHARED_9B_OK"
MARKER = "<!-- foundation-humanmodel-9b-e2e-receipt:v1:"
QUESTION = "When choosing a career opportunity, do I prefer predictable evenings or a higher title?"
_CONTENT = "For this period I prefer predictable evenings over pursuing a higher title."


def valid_owner_event(event, live):
    if type(event) is not dict or event.get("action") != "opened":
        return False
    if event.get("repository", {}).get("full_name") != REPO:
        return False
    row = event.get("issue", {})
    return (type(row) is dict and type(row.get("number")) is int
            and row["number"] > 0
            and (row.get("title"), row.get("body")) in
                ((TITLE, BODY), (CHAT_TITLE, CHAT_BODY)) and row.get("state") == "open"
            and row.get("user", {}).get("login") == "quest7070-debug"
            and type(live) is dict and live.get("number") == row["number"]
            and live.get("title") == row.get("title") and live.get("body") == row.get("body")
            and live.get("state") == "open"
            and live.get("user", {}).get("login") == "quest7070-debug")


# A 1-minute CPU load average can still reflect dependency installation after
# the runner has finished that work. Let it settle in the *existing* compute
# lease; never relax the CPU/RAM thresholds or start another model.
CPU_SETTLE_MAX_SECONDS = 75
CPU_SETTLE_POLL_SECONDS = 15


def wait_for_admission(*, observe, monotonic=time.monotonic, pause=time.sleep):
    """Bounded low-load retries; recheck pinned identity and memory each time."""
    deadline = monotonic() + CPU_SETTLE_MAX_SECONDS
    while True:
        verdict = observe()
        # Other resident models, memory pressure, unknown inventory and all
        # other failures are definitive for this one attempt: never retry them.
        if verdict != "BLOCKED_CPU_PRESSURE":
            return verdict
        remaining = deadline - monotonic()
        if remaining <= 0:
            return verdict
        pause(min(CPU_SETTLE_POLL_SECONDS, remaining))


def admission():
    tags = _local_json("/api/tags", timeout=3)
    resident = _local_json("/api/ps", timeout=3)
    result = _model_gate(tags, resident)
    if result == "BLOCKED_PINNED_9B_NOT_RESIDENT":
        result = _cold_start_gate(tags, resident)
    return result


class SyntheticLocal9B:
    """Real loopback 9B, no cloud, no tool dispatch or untrusted model selection."""
    def __init__(self, diagnosis=None, timeout=180):
        if type(timeout) is not int or not 30 <= timeout <= 900:
            raise ValueError("LOCAL_9B_TIMEOUT_OUT_OF_RANGE")
        self.calls = 0
        self.diagnosis = diagnosis
        self.timeout = timeout

    def _status(self, value):
        if self.diagnosis is not None:
            self.diagnosis["model_state"] = value

    def chat_payload(self, payload, model=None):
        if model != MODEL or type(payload) is not dict:
            raise ValueError("LOCAL_9B_ONLY")
        messages = payload.get("messages")
        if (type(messages) is not list or not 1 <= len(messages) <= 8
                or payload.get("tools") or
                any(type(m) is not dict or m.get("role") not in {"system", "user"}
                    or type(m.get("content")) is not str
                    for m in messages)):
            raise ValueError("TOOL_FREE_BOUNDED_MESSAGES_REQUIRED")
        if len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) > 32768:
            raise ValueError("SYNTHETIC_PROMPT_TOO_LARGE")
        self.calls += 1
        if self.diagnosis is not None:
            self.diagnosis["model_calls"] = self.calls
            self.diagnosis["phase"] = "MODEL_REQUEST"
        self._status("MODEL_IO_PENDING")
        try:
            response = _local_json("/api/chat", {
                "model": MODEL, "stream": False, "think": False,
                "messages": messages,
                "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 640},
            }, timeout=self.timeout)
        except Exception as exc:
            # Only a fixed category leaves the owner-local runner, never error
            # text, server body, model response, prompt, or file paths.
            from urllib.error import HTTPError, URLError
            if isinstance(exc, HTTPError):
                code = exc.code
                self._status("MODEL_HTTP_4XX" if 400 <= code < 500
                             else "MODEL_HTTP_5XX" if 500 <= code < 600
                             else "MODEL_HTTP_OTHER")
            elif isinstance(exc, (TimeoutError,)):
                self._status("MODEL_TIMEOUT")
            elif isinstance(exc, URLError):
                self._status("MODEL_TRANSPORT")
            else:
                self._status("MODEL_TRANSPORT_OR_JSON")
            raise
        self._status("MODEL_HTTP_OK")
        message = response.get("message")
        if response.get("done_reason") != "stop":
            self._status("MODEL_FINISH_LENGTH" if response.get("done_reason") == "length"
                         else "MODEL_FINISH_OTHER")
            raise ValueError("LOCAL_9B_ANSWER_UNVERIFIED")
        if (response.get("model") != MODEL or response.get("done") is not True
                or type(message) is not dict or message.get("tool_calls")
                or message.get("thinking") not in (None, "")
                or type(message.get("content")) is not str
                or not 0 < len(message["content"]) <= 8192):
            self._status("MODEL_REPLY_INVALID")
            raise ValueError("LOCAL_9B_ANSWER_UNVERIFIED")
        self._status("MODEL_REPLY_VALID")
        return {"model": MODEL, "choices": [{"message": {
            "content": message["content"]}}]}


class OnlyPinnedLocalRoute:
    settings = None

    def choose(self, function, *, exclude=(), local_required=False):
        if function != "CHAT" or local_required is not True:
            raise PermissionError("PRIVATE_LOCAL_ROUTE_REQUIRED")
        if "synthetic-local9b" in exclude:
            return SimpleNamespace(binding=None)
        return SimpleNamespace(binding="synthetic-local9b", kind="LOCAL",
                               execution_slot=MODEL, model=MODEL)


def run_synthetic_e2e(diagnosis=None):
    if diagnosis is not None:
        diagnosis["phase"] = "SYNTHETIC_LEDGER"
    from ai_foundation.auto_agent import AutoCapabilityAgent
    from ai_foundation.capability_request import CapabilityRequest
    from ai_foundation.core import GuardState
    from ai_foundation.guard import GuardCore
    from ai_foundation.human_model_context import (
        HumanModelBinding, HumanModelContext, _source_reader,
    )
    from ai_foundation.routed_agent_model import foundation_agent_model
    from human_model_ledger import Ledger

    with TemporaryDirectory(prefix="hm9b-synthetic-") as tmp:
        volumes = Path(tmp) / "Volumes"
        root = volumes / "USB" / "HumanModel"
        (root / "ledger").mkdir(parents=True)
        ledger = Ledger(root / "ledger" / "human_model.sqlite3")
        try:
            eid = ledger.add(
                source_uri="synthetic:career", source_revision="1",
                kind="decision", scope="career", content=_CONTENT,
                privacy="private", observed_at="2026-11-13T00:00:00Z")
            ledger.define_view(
                view_id="synthetic-approved", purpose="synthetic owner answer",
                audience="foundation", allowed_scopes=["career"])
            ledger.rebuild_view(view_id="synthetic-approved")
            if diagnosis is not None:
                diagnosis["phase"] = "VIEW_READY"

            reader = partial(_source_reader(ROOT), volumes_dir=volumes,
                             mount_check=lambda p: p == str(volumes / "USB"))
            context = HumanModelContext(
                HumanModelBinding("synthetic-owner", str(root),
                                  "synthetic-approved", ("career",), "private"),
                reader, guard=GuardCore(GuardState()),
                run_id="synthetic-humanmodel-e2e")
            endpoint = SyntheticLocal9B(diagnosis)
            model = foundation_agent_model(
                OnlyPinnedLocalRoute(),
                lambda _: (_ for _ in ()).throw(PermissionError("CLOUD_FORBIDDEN")),
                endpoint, local_required=True)
            agent = AutoCapabilityAgent(
                model, object(), CapabilityRequest(
                    capability="CHAT", owner_id="synthetic-owner"),
                human_model_context=context, run_id="synthetic-humanmodel-e2e")
            if diagnosis is not None:
                diagnosis["phase"] = "OWNER_ANSWER_REQUESTED"
            answer = agent.answer_owner_question(QUESTION, scope="career")
            if diagnosis is not None and diagnosis.get("model_state") == "MODEL_REPLY_VALID":
                diagnosis["phase"] = "ANSWER_RETURNED"
            valid = (
                answer.get("status") == "SIMULATED_PROVISIONAL"
                and answer.get("citation_reference_status") == "MATCHED_IDS_ONLY"
                and answer.get("cited_evidence_ids") == [eid]
                and answer.get("execution_authority") is False
                and answer.get("owner_statement_verified") is False
                and endpoint.calls == 1
            )
            allowed_reasons = {
                "OWNER_ANSWER_WITHOUT_SOURCE_CITATION",
                "UNSUPPORTED_EVIDENCE_CITATION",
                "OWNER_SIMULATION_INVALID_TOOL_REQUEST",
                "OWNER_SIMULATION_ROUTE_UNAVAILABLE",
                "VIEW_CHANGED_DURING_SIMULATION",
                "NO_SIMULATED_ANSWER",
                "NO_RELEVANT_OWNER_EVIDENCE",
            }
            reason = answer.get("reason")
            route_failed = reason == "OWNER_SIMULATION_ROUTE_UNAVAILABLE"
            safe_codes = {
                "NO_ELIGIBLE_ROUTE", "MODEL_TIMEOUT", "MODEL_HTTP_4XX",
                "MODEL_HTTP_5XX", "MODEL_POLICY_DENIED",
                "MODEL_RESPONSE_INVALID", "MODEL_TRANSPORT", "MODEL_EXECUTION",
            }
            failure_code = answer.get("model_failure_code")
            failure_phase = answer.get("model_failure_phase")
            attempts = answer.get("model_attempts")
            refs = answer.get("cited_evidence_ids")
            return {
                "status": "LIVE_SYNTHETIC_CITED_ANSWER" if valid else "NOT_ACCEPTED",
                "reason": ("VERIFIED" if valid else
                           "MODEL_ROUTE_UNAVAILABLE" if route_failed else
                           "MODEL_OUTPUT_NOT_EVIDENCE_BOUND"),
                "model_failure_code": (failure_code if route_failed and
                                       failure_code in safe_codes else "NOT_APPLICABLE"),
                "model_failure_phase": (failure_phase if route_failed and
                                        failure_phase in ("initial", "tool_followup")
                                        else "NOT_APPLICABLE"),
                "model_attempts": (attempts if route_failed and type(attempts) is int
                                   and 0 <= attempts <= 8 else 0),
                "answer_status": answer.get("status") if answer.get("status")
                                 in ("SIMULATED_PROVISIONAL", "UNAVAILABLE") else "OTHER",
                "answer_reason": reason if reason in allowed_reasons else "NOT_APPLICABLE",
                "cited_count": len(refs) if type(refs) is list
                               and len(refs) <= 12 else 0,
                "model_calls": endpoint.calls,
                "model": MODEL, "private_owner_records_read": 0,
                "owner_answer_fidelity": "NOT_EVALUATED",
            }
        finally:
            ledger.close()


def run_shared_chat_route(diagnosis):
    """One fixed public request through the actual new shared execution adapter."""
    from ai_foundation.shared_ollama9b_adapter import SharedOllama9BExecution
    execution = SharedOllama9BExecution()
    diagnosis["phase"] = "SHARED_CHAT_REQUESTED"
    try:
        reply = execution.chat_payload({
            "messages": [{"role": "user", "content":
                "Reply with exactly " + _CHAT_REPLY + " and nothing else."}],
            "max_tokens": 256, "temperature": 0,
        }, model="general")
    finally:
        diagnosis["model_calls"] = execution.calls
    choices = reply.get("choices") if type(reply) is dict else None
    choice = choices[0] if type(choices) is list and len(choices) == 1 else {}
    message = choice.get("message") if type(choice) is dict else None
    valid = (reply.get("model") == MODEL and type(message) is dict
             and message.get("role") == "assistant" and not message.get("tool_calls")
             and type(message.get("content")) is str
             and message["content"].strip() == _CHAT_REPLY
             and choice.get("finish_reason") == "stop" and execution.calls == 1)
    diagnosis["phase"] = "SHARED_CHAT_RETURNED"
    diagnosis["model_state"] = "MODEL_REPLY_VALID" if valid else "MODEL_REPLY_INVALID"
    return {"status": "LIVE_SHARED_CHAT_ANSWER" if valid else "NOT_ACCEPTED",
            "reason": "VERIFIED" if valid else "SHARED_CHAT_REPLY_UNVERIFIED",
            "model_calls": execution.calls, "private_owner_records_read": 0,
            "owner_answer_fidelity": "NOT_EVALUATED"}


def execute():
    if (os.environ.get("GITHUB_REPOSITORY") != REPO
            or os.environ.get("GITHUB_WORKFLOW") != WORKFLOW
            or os.environ.get("GITHUB_EVENT_NAME") != "issues"
            or not re.fullmatch(r"[0-9]{1,20}",
                                os.environ.get("GITHUB_RUN_ID", ""))):
        raise ValueError("INVALID_OWNER_RUN_CONTEXT")
    token = os.environ.get("GITHUB_TOKEN")
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not token or not path:
        raise ValueError("OWNER_ISSUE_CONTEXT_REQUIRED")
    event = json.loads(Path(path).read_text())
    number = event.get("issue", {}).get("number")
    if type(number) is not int or number < 1:
        raise ValueError("OWNER_ISSUE_MISSING")
    prefix = "/repos/" + REPO + "/issues/" + str(number)
    live = bridge._github_api("GET", prefix, token)
    if not valid_owner_event(event, live):
        raise PermissionError("OWNER_ISSUE_AUTHORIZATION_REJECTED")
    comments = bridge._github_api(
        "GET", prefix + "/comments?per_page=100", token)
    if (type(comments) is not list or len(comments) >= 100
            or any(MARKER + str(number) + " -->" in c.get("body", "")
                   for c in comments if type(c) is dict)):
        raise ValueError("RECEIPT_ALREADY_PRESENT_OR_HISTORY_UNBOUNDED")
    bridge.require_m1()
    diagnosis = {"phase": "ADMISSION", "model_state": "MODEL_NOT_CALLED",
                 "model_calls": 0}
    try:
        gate = wait_for_admission(observe=admission)
        if gate not in {"READY_EXISTING_9B", "READY_SAFE_COLD_START_9B"}:
            result = {"status": "BLOCKED", "reason": gate, "model_calls": 0}
        else:
            result = (run_shared_chat_route(diagnosis)
                      if event["issue"]["title"] == CHAT_TITLE
                      else run_synthetic_e2e(diagnosis))
    except Exception as exc:
        # No exception strings, source data, model replies or paths in Actions.
        safe = {"OSError", "TimeoutError", "HTTPError", "URLError",
                "ValueError", "PermissionError", "RuntimeError"}
        result = {"status": "NOT_ACCEPTED", "reason": "HOST_OR_MODEL_ERROR",
                  "error_class": type(exc).__name__ if type(exc).__name__ in safe
                  else "OTHER", "model_calls": diagnosis["model_calls"]}
    result.update({
        "schema": 1, "synthetic_only": True, "no_private_content_export": True,
        "owner_fidelity_accepted": False,
        "phase": diagnosis["phase"], "model_state": diagnosis["model_state"],
    })
    bridge._github_api("POST", prefix + "/comments", token, {
        "body": MARKER + str(number) + " -->\n"
                + "Synthetic HumanModel → pinned local 9B acceptance (no owner data)\n\n"
                + "~~~json\n" + json.dumps(result, sort_keys=True) + "\n~~~"})
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"LIVE_SYNTHETIC_CITED_ANSWER",
                                    "LIVE_SHARED_CHAT_ANSWER"} else 1


if __name__ == "__main__":
    raise SystemExit(execute())
