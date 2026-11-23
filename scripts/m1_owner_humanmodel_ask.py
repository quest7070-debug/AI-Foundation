#!/usr/bin/env python3
"""Owner-session HumanModel Q&A from this M1 only.

Composes the EXISTING approved-view binding, read-only Guard and pinned
local 9B exactly as the owner real-view E2E does, but takes one bounded
question from the local operator session (the owner's agent) and prints
the provisional, citation-bearing answer as JSON on stdout.

No listener, no network beyond loopback Ollama, no cloud route and no
write path: collection, correction and refresh are not offered here.
Only the view registered in the host bindings can be questioned; the
private owner-profile view is not registered and stays unreachable
from this entry point.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
for path in ("src", "scripts", "experiments/human_model"):
    sys.path.insert(0, str(ROOT / path))

RUN_ID = "m1-owner-ask-local"
MAX_QUESTION_CHARS = 2048


def validate_question(raw):
    if type(raw) is not str or not raw.strip() or len(raw) > MAX_QUESTION_CHARS:
        raise ValueError("BOUNDED_OWNER_QUESTION_REQUIRED")
    return raw.strip()


def ask(question):
    from ai_foundation.auto_agent import AutoCapabilityAgent
    from ai_foundation.capability_request import CapabilityRequest
    from ai_foundation.human_model_context import HumanModelContext, _source_reader
    from ai_foundation.routed_agent_model import foundation_agent_model
    from m1_humanmodel_9b_synthetic_e2e import (
        OnlyPinnedLocalRoute, SyntheticLocal9B, admission, wait_for_admission)
    from m1_owner_humanmodel_real_e2e import installed_owner_binding

    gate = wait_for_admission(observe=admission)
    if gate not in ("READY_EXISTING_9B", "READY_SAFE_COLD_START_9B"):
        return {"status": "BLOCKED", "reason": gate,
                "execution_authority": False}
    owner, binding, guard = installed_owner_binding()
    context = HumanModelContext(
        binding, _source_reader(ROOT), guard=guard, run_id=RUN_ID)
    diagnosis = {"model_calls": 0, "model_state": "MODEL_NOT_CALLED"}
    endpoint = SyntheticLocal9B(diagnosis, timeout=600)
    model = foundation_agent_model(
        OnlyPinnedLocalRoute(),
        lambda _: (_ for _ in ()).throw(PermissionError("CLOUD_FORBIDDEN")),
        endpoint, local_required=True)
    agent = AutoCapabilityAgent(
        model, object(), CapabilityRequest(capability="CHAT", owner_id=owner),
        human_model_context=context, run_id=RUN_ID)
    answer = agent.answer_owner_question(question, scope=binding.scopes[0])
    return {**answer, "model_state": diagnosis.get("model_state"),
            "view_id": binding.view_id, "scope": binding.scopes[0]}


def main(argv):
    if (platform.system() != "Darwin" or os.getuid() != os.geteuid()
            or os.getuid() != 501):
        print(json.dumps({"status": "BLOCKED",
                          "reason": "OWNER_M1_SESSION_REQUIRED"}))
        return 2
    if len(argv) != 2:
        print(json.dumps({"status": "BLOCKED",
                          "reason": "EXACTLY_ONE_QUESTION_REQUIRED"}))
        return 2
    try:
        question = validate_question(argv[1])
    except ValueError:
        print(json.dumps({"status": "BLOCKED",
                          "reason": "BOUNDED_OWNER_QUESTION_REQUIRED"}))
        return 2
    try:
        result = ask(question)
    except Exception:
        print(json.dumps({"status": "UNAVAILABLE",
                          "reason": "OWNER_ASK_RUNTIME_UNAVAILABLE",
                          "execution_authority": False}))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "SIMULATED_PROVISIONAL" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
