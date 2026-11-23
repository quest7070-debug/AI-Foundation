#!/usr/bin/env python3
"""One real pinned M1 9B text request without dependency installation.

The probe contains no owner context, persistent effect or model-selection input.
It uses the same host compute lease and conservative 9B CPU/RAM gate.
An exact owner Issue provides a remote request, or --local runs on the owner Mac.
Neither route downloads a model or force-stops a shared process.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
from urllib import request

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from ai_foundation.host_compute_lease import (
    HostComputeBusy, HostComputeLease, HostComputeLeaseError,
)
from ai_foundation.klm_compute_admission import (
    AVAILABLE, CPU_PRESSURE, admit_local_9b,
)
import m1_development_bridge as bridge

MODEL = "qwen3.5:9b"
DIGEST = "56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90"
ANSWER = "FOUNDATION_LOCAL9B_OK"
REPO = "quest7070-dev/AI-Foundation"
OWNER = "quest7070-debug"
WORKFLOW = "Foundation M1 HumanModel synthetic 9B E2E"
TITLE = "Foundation M1 9B stdlib real smoke"
BODY = "<!-- foundation-m1-9b-stdlib-smoke:v1 -->"
MARKER = "<!-- foundation-m1-9b-stdlib-smoke-receipt:v1:"
MAX_CPU_WAIT = 150
POLL_SECONDS = 15


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = request.build_opener(request.ProxyHandler({}), _NoRedirect())


def loopback(path, payload=None, *, timeout=3):
    """Fixed Ollama loopback requests; never export server text on failures."""
    if path not in ("/api/tags", "/api/ps", "/api/chat"):
        raise ValueError("UNAPPROVED_OLLAMA_OPERATION")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(
        "http://127.0.0.1:11434" + path, data=data,
        method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json"},
    )
    with OPENER.open(req, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError("OLLAMA_NON_200")
        raw = response.read(131073)
    if len(raw) > 131072:
        raise ValueError("OLLAMA_REPLY_TOO_LARGE")
    obj = json.loads(raw)
    if type(obj) is not dict:
        raise ValueError("OLLAMA_REPLY_NOT_OBJECT")
    return obj


def exact_model_state(tags, resident):
    """No other loaded Ollama model, exact installed and resident identities."""
    available = tags.get("models") if type(tags) is dict else None
    loaded = resident.get("models") if type(resident) is dict else None
    if type(available) is not list or type(loaded) is not list:
        return "BLOCKED_MODEL_INVENTORY_INVALID"
    if not any(type(m) is dict and m.get("name") == MODEL
               and m.get("digest") == DIGEST for m in available):
        return "BLOCKED_PINNED_9B_NOT_INSTALLED"
    if loaded:
        if (len(loaded) != 1 or type(loaded[0]) is not dict
                or loaded[0].get("name", loaded[0].get("model")) != MODEL
                or loaded[0].get("digest") != DIGEST):
            return "BLOCKED_OTHER_RESIDENT_MODEL"
        return "READY_EXISTING_9B"
    return "READY_COLD_START_CHECK"


def fixed_probe(*, transport=loopback, admission=admit_local_9b,
                now=time.monotonic, sleep=time.sleep):
    """One real request after repeated fresh identity/CPU/RAM checks."""
    calls = 0
    deadline = now() + MAX_CPU_WAIT
    try:
        with HostComputeLease().hold(max_wait_s=20):
            while True:
                state = exact_model_state(
                    transport("/api/tags"), transport("/api/ps"))
                if state == "READY_COLD_START_CHECK":
                    accepted, reason = admission()
                    state = ("READY_SAFE_COLD_START_9B" if accepted and reason == AVAILABLE
                             else "BLOCKED_CPU_PRESSURE" if reason == CPU_PRESSURE
                             else "BLOCKED_LOCAL_RESOURCES")
                if state != "BLOCKED_CPU_PRESSURE" or now() >= deadline:
                    break
                sleep(min(POLL_SECONDS, deadline - now()))
            if state not in ("READY_EXISTING_9B", "READY_SAFE_COLD_START_9B"):
                return {"status": "BLOCKED", "reason": state, "model_calls": 0}

            payload = {
                "model": MODEL, "stream": False, "think": False,
                "keep_alive": "2m",
                "messages": [{"role": "user", "content":
                              "Reply with exactly " + ANSWER + " and nothing else."}],
                "options": {"temperature": 0, "num_ctx": 2048, "num_predict": 64},
            }
            calls = 1
            response = transport("/api/chat", payload, timeout=110)
            message = response.get("message")
            valid = (response.get("model") == MODEL
                     and response.get("done") is True
                     and response.get("done_reason") == "stop"
                     and type(message) is dict
                     and not message.get("tool_calls")
                     and message.get("thinking") in ("", None)
                     and type(message.get("content")) is str
                     and message["content"].strip() == ANSWER)
            return {
                "status": "LIVE_PINNED_9B_ANSWER" if valid else "NOT_ACCEPTED",
                "reason": "VERIFIED" if valid else "MODEL_REPLY_UNVERIFIED",
                "model_calls": calls, "private_owner_records_read": 0,
                "model_identity": "PINNED_9B", "humanmodel_e2e": False,
            }
    except (HostComputeBusy, HostComputeLeaseError):
        return {"status": "BLOCKED", "reason": "HOST_COMPUTE_LEASE_UNAVAILABLE",
                "model_calls": calls}
    except Exception:
        # Never copy URLs, server bodies, process text or private data.
        return {"status": "NOT_ACCEPTED", "reason": "LOCAL_MODEL_IO_UNVERIFIED",
                "model_calls": calls}


def owner_issue(event, live):
    issue = event.get("issue") if type(event) is dict else None
    return (
        type(issue) is dict and event.get("action") == "opened"
        and event.get("repository", {}).get("full_name") == REPO
        and event.get("sender", {}).get("login") == OWNER
        and type(issue.get("number")) is int and issue["number"] > 0
        and issue.get("user", {}).get("login") == OWNER
        and issue.get("state") == "open"
        and issue.get("title") == TITLE and issue.get("body") == BODY
        and type(live) is dict
        and all(live.get(k) == issue.get(k)
                for k in ("number", "state", "title", "body"))
        and live.get("user", {}).get("login") == OWNER
    )


def run_issue():
    if (os.environ.get("GITHUB_REPOSITORY") != REPO
            or os.environ.get("GITHUB_WORKFLOW") != WORKFLOW
            or os.environ.get("GITHUB_EVENT_NAME") != "issues"
            or os.environ.get("GITHUB_ACTOR") != OWNER
            or not re.fullmatch(r"[0-9]{1,20}", os.environ.get("GITHUB_RUN_ID", ""))):
        raise PermissionError("OWNER_WORKFLOW_REQUIRED")
    token, event_path = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_EVENT_PATH")
    if not token or not event_path:
        raise PermissionError("OWNER_ISSUE_CONTEXT_REQUIRED")
    event = json.loads(Path(event_path).read_text())
    number = event.get("issue", {}).get("number")
    if type(number) is not int or number < 1:
        raise PermissionError("OWNER_ISSUE_IDENTITY_REQUIRED")
    prefix = "/repos/" + REPO + "/issues/" + str(number)
    live = bridge._github_api("GET", prefix, token)
    if not owner_issue(event, live):
        raise PermissionError("OWNER_ISSUE_CHANGED")
    sha = os.environ.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise PermissionError("PINNED_SOURCE_REQUIRED")
    checkout = subprocess.run(["/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=5, check=False)
    if checkout.returncode != 0 or checkout.stdout.strip() != sha:
        raise PermissionError("CHECKOUT_COMMIT_MISMATCH")
    comments = bridge._github_api("GET", prefix + "/comments?per_page=100", token)
    if (type(comments) is not list or len(comments) >= 100
            or any(type(c) is dict and MARKER + str(number) + " -->" in c.get("body", "")
                   for c in comments)):
        raise PermissionError("DUPLICATE_OR_UNBOUNDED_RECEIPT")
    result = fixed_probe()
    result.update({"schema": 1, "owner_records_exported": 0, "paid_calls": 0})
    bridge._github_api("POST", prefix + "/comments", token, {
        "body": MARKER + str(number) + " -->\n\n~~~json\n"
                + json.dumps(result, sort_keys=True) + "\n~~~",
    })
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "LIVE_PINNED_9B_ANSWER" else 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if (platform.system() != "Darwin"
            or platform.machine() not in ("arm64", "aarch64")
            or os.getuid() != 501 or os.geteuid() != 501):
        raise PermissionError("OWNER_M1_REQUIRED")
    if argv == ["--local"]:
        result = fixed_probe()
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "LIVE_PINNED_9B_ANSWER" else 1
    if argv:
        raise ValueError("UNSUPPORTED_ARGUMENTS")
    return run_issue()


if __name__ == "__main__":
    raise SystemExit(main())
