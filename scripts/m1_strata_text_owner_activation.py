#!/usr/bin/env python3
"""One-shot owner-triggered, pinned Strata PUBLIC CHAT config activation on M1.

Requires the *running* Operator to already contain the source-level privacy
gate. Changes exactly one existing pinned 0600 endpoint JSON. Does not restart
Operator or models, read bearer keys, invoke inference or mutate Guard/Work.
A separate existing Guard-approved Operator release reloads the config.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import stat
import subprocess
import sys
from urllib import request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from m1_direct_development import installed_config
from m1_strata_local_first_setup import configure_strata
from m1_operator_release_host import FixedOperatorHost, LABEL

REPO = "quest7070-dev/AI-Foundation"
OWNER = "quest7070-debug"
WORKFLOW = "Foundation M1 Strata public text activation"
PREFIX = "Foundation M1 Strata Text Activate: "
MARKER = "<!-- foundation-strata-text-activation-receipt:v1:"
VERIFY_PREFIX = "Foundation M1 Strata Text Verify: "
VERIFY_MARKER = "<!-- foundation-strata-text-verification-receipt:v1:"
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SOURCES = (
    "scripts/operator_server.py",
    "src/ai_foundation/compute_routing.py",
    "src/ai_foundation/inference_service.py",
    "src/ai_foundation/model_work_roles.py",
    "src/ai_foundation/inference_composition.py",
    "src/ai_foundation/local_endpoint_config.py",
)

class Denied(ValueError):
    pass

def insist(ok, reason):
    if not ok:
        raise Denied(reason)

def identity(event, env, live=None, *, verify=False):
    issue = event.get("issue") if type(event) is dict else None
    sha = env.get("GITHUB_SHA")
    title_prefix = VERIFY_PREFIX if verify else PREFIX
    body_prefix = ("<!-- foundation-strata-text-verify:v1:" if verify else
                   "<!-- foundation-strata-text-activation:v1:")
    insist(
        env.get("GITHUB_REPOSITORY") == REPO
        and env.get("GITHUB_WORKFLOW") == WORKFLOW
        and env.get("GITHUB_EVENT_NAME") == "issues"
        and env.get("GITHUB_ACTOR") == OWNER
        and type(sha) is str and SHA40.fullmatch(sha) is not None
        and event.get("action") == "opened"
        and event.get("sender", {}).get("login") == OWNER
        and event.get("repository", {}).get("full_name") == REPO
        and type(issue) is dict and type(issue.get("number")) is int
        and issue.get("state") == "open"
        and issue.get("user", {}).get("login") == OWNER
        and issue.get("title") == title_prefix + sha
        and issue.get("body") == body_prefix + sha + " -->",
        "EXACT_OWNER_ISSUE_REQUIRED",
    )
    if live is not None:
        insist(type(live) is dict
               and all(live.get(k) == issue.get(k)
                       for k in ("number", "title", "body", "state"))
               and live.get("user", {}).get("login") == OWNER,
               "LIVE_OWNER_ISSUE_CHANGED")
    return issue["number"]

def github(token, suffix, method="GET", data=None):
    insist(type(token) is str and bool(token), "GITHUB_TOKEN_UNAVAILABLE")
    insist(re.fullmatch(r"/issues/[0-9]+(?:/comments(?:\?per_page=100)?)?", suffix)
           is not None, "GITHUB_SCOPE_DENIED")
    url = "https://api.github.com/repos/" + REPO + suffix
    req = request.Request(
        url, method=method,
        data=None if data is None else json.dumps(data, sort_keys=True).encode(),
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "foundation-m1-strata-text-activation",
                 **({"Content-Type": "application/json"} if data is not None else {})})
    with request.urlopen(req, timeout=15) as response:
        raw = response.read(65537)
    insist(len(raw) <= 65536, "GITHUB_RECEIPT_OVERSIZE")
    return json.loads(raw)

def owner_live_source():
    insist(platform.system() == "Darwin" and platform.machine() in ("arm64", "aarch64")
           and os.getuid() == os.geteuid() == 501,
           "OWNER_M1_SESSION_REQUIRED")
    head = subprocess.run(
        ["/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=8, check=False)
    insist(head.returncode == 0 and head.stdout.strip() == os.environ["GITHUB_SHA"],
           "PINNED_MAIN_SOURCE_REQUIRED")
    host = FixedOperatorHost(ROOT)
    insist(host._registered() and host._pid_owned(), "OPERATOR_PID_NOT_BOUND")
    human = host._human()
    insist(type(human) is dict and type(human.get("activity")) is list
           and not human["activity"], "OPERATOR_NOT_IDLE")
    plist = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
    info = plist.lstat()
    insist(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
           and not (info.st_mode & 0o022) and info.st_size <= 32768,
           "OPERATOR_PLIST_UNTRUSTED")
    row = plistlib.loads(plist.read_bytes())
    args = row.get("ProgramArguments")
    wd = row.get("WorkingDirectory")
    insist(row.get("Label") == LABEL and type(args) is list
           and type(wd) is str and wd.startswith("/")
           and ".." not in Path(wd).parts, "OPERATOR_SOURCE_UNVERIFIED")
    installed = Path(wd)
    insist(installed.is_dir() and not installed.is_symlink(),
           "OPERATOR_SOURCE_UNVERIFIED")
    entry = installed / "scripts/operator_server.py"
    insist(args.count(str(entry)) == 1, "OPERATOR_ENTRY_UNVERIFIED")
    paths = row.get("EnvironmentVariables", {}).get("PYTHONPATH", "")
    insist(type(paths) is str and paths.split(":")[0] == str(installed / "src"),
           "OPERATOR_IMPORT_PATH_CHANGED")
    # A verified Git SHA does not prove the running process loaded these
    # modules. The PID must also be bound to the inspected LaunchAgent.
    for rel in SOURCES:
        source, candidate = installed / rel, ROOT / rel
        insist(source.is_file() and not source.is_symlink()
               and candidate.is_file() and not candidate.is_symlink()
               and source.stat().st_size <= 2_000_000
               and hashlib.sha256(source.read_bytes()).digest()
                   == hashlib.sha256(candidate.read_bytes()).digest(),
               "OPERATOR_PRIVACY_GATE_SOURCE_MISMATCH")
    return host

def activate():
    host = owner_live_source()
    _config_path, config, root = installed_config()
    # Existing setup validates owner/private file permissions, pinned model
    # identity, exact fixed 18080 direct-link address and other endpoints.
    prior = configure_strata(root, port=18080, expand_text_roles=True)
    insist(prior in ("READY_TO_EXPAND_TEXT", "ALREADY_TEXT_ENABLED",
                     "ALREADY_CONFIGURED"),
           "STRATA_EXISTING_CONFIG_REVIEW_REQUIRED")
    if prior == "READY_TO_EXPAND_TEXT":
        insist(configure_strata(root, port=18080, expand_text_roles=True,
                               apply=True) == "TEXT_ROLES_EXPANDED",
               "STRATA_TEXT_CONFIG_WRITE_UNVERIFIED")
    insist(configure_strata(root, port=18080, expand_text_roles=True)
           in ("ALREADY_TEXT_ENABLED", "ALREADY_CONFIGURED"),
           "STRATA_TEXT_CONFIG_READBACK_FAILED")
    insist(host._registered() and host._pid_owned(), "OPERATOR_PID_CHANGED")
    # Already running composition retains its in-memory capability snapshot.
    # Never claim the new CHAT route is live without a separately Guard-approved
    # Operator restart and a real authenticated public-text model call.
    return {"status": "CONFIGURED_RESTART_REQUIRED",
            "config_changed": prior == "READY_TO_EXPAND_TEXT",
            "model_calls": 0, "service_mutations": 0, "private_egress": False}


def public_chat_probe_child():
    """One fixed synthetic non-CODE text request. Never returns model text."""
    import time
    from ai_foundation.compute_routing import ComputeRouter
    from ai_foundation.local_compute_registry import LocalComputeRegistry
    from ai_foundation.native_credentials import MacOSNativeCredentialStore
    from ai_foundation.openai_local_adapter import (
        OpenAILocalDiscovery, OpenAILocalExecution, OpenAILocalModelPolicy,
    )
    insist(platform.system() == "Darwin" and platform.machine() in ("arm64", "aarch64")
           and os.getuid() == os.geteuid() == 501,
           "OWNER_M1_SESSION_REQUIRED")
    _cfg, _settings, root = installed_config()
    insist(configure_strata(root, port=18080, expand_text_roles=True)
           in ("ALREADY_TEXT_ENABLED", "ALREADY_CONFIGURED"),
           "STRATA_CHAT_CONFIG_NOT_ENABLED")
    try:
        key = MacOSNativeCredentialStore().load("local:mainpc-strata:api-key")
    except (OSError, KeyError, ValueError, RuntimeError):
        return {"status": "BLOCKED", "reason": "OWNER_KEYCHAIN_UNAVAILABLE",
                "model_calls": 0}
    if type(key) is not str or not 16 <= len(key) <= 256:
        return {"status": "BLOCKED", "reason": "OWNER_KEYCHAIN_UNAVAILABLE",
                "model_calls": 0}
    model = "qwen3.8-flash-next-coder-iq1_m"
    binding = "local:mainpc-strata:code-agent"
    base = "http://10.0.1.1:18080"
    policy = OpenAILocalModelPolicy(
        model, "code-agent", ("CODE", "CHAT"),
        ("DEVELOPMENT_AGENT", "PUBLIC_SUMMARIZATION"))
    discovery = LocalComputeRegistry(OpenAILocalDiscovery(
        base, binding_prefix="local:mainpc-strata",
        allowed_hosts=("10.0.1.1",), models=(policy,),
        api_key=key, timeout=3))
    # Single bounded authenticated discovery read. Do not perform an extra
    # network probe merely to decide the route or expose raw server responses.
    # The canonical router still chooses from that exact observed snapshot.
    try:
        candidates = discovery.candidates()
    except Exception:
        return {"status": "BLOCKED", "reason": "DISCOVERY_RUNTIME_UNAVAILABLE",
                "model_calls": 0}
    selected = ComputeRouter(
        None, LocalComputeRegistry(lambda: candidates)
    ).choose("CHAT", strata_first=True)
    if (selected.binding != binding or selected.execution_slot != "code-agent"
            or selected.model != model):
        known = {
            "HTTP_401", "HTTP_403", "HTTP_429", "HTTP_500", "HTTP_502",
            "HTTP_503", "HTTP_504", "NO_AUTHORIZED_MODEL", "URLError",
            "TimeoutError", "JSONDecodeError",
        }
        observed = next((item.reason for item in candidates
                         if item.reason in known), None)
        return {"status": "BLOCKED",
                "reason": "DISCOVERY_" + observed
                          if observed else "PINNED_REMOTE_CHAT_UNAVAILABLE",
                "model_calls": 0}
    execution = OpenAILocalExecution(
        base, allowed_hosts=("10.0.1.1",),
        alias_to_model={"code-agent": model},
        api_key=key, timeout=55, request_defaults={"max_tokens": 128})
    fixed_public = (
        "Summarize in one concise sentence: "
        "A MainPC drafts public changes, and an M1 checks the results independently."
    )
    start = time.perf_counter()
    # Exactly one authenticated request, no tools, private data or retries.
    try:
        response = execution.chat_payload({
            "messages": [{"role": "user", "content": fixed_public}],
            "temperature": 0, "max_tokens": 128,
        }, model=selected.execution_slot)
    except Exception:
        return {"status": "BLOCKED", "reason": "REMOTE_CHAT_EXECUTION_UNVERIFIED",
                "model_calls": 1}
    latency_ms = int(min(100000, max(0, (time.perf_counter() - start) * 1000)))
    choices = response.get("choices") if type(response) is dict else None
    choice = choices[0] if type(choices) is list and len(choices) == 1 else None
    message = choice.get("message") if type(choice) is dict else None
    answer = message.get("content") if type(message) is dict else None
    if (type(answer) is not str or len(answer) < 8 or len(answer) > 2048
            or "MainPC" not in answer or "M1" not in answer
            or choice.get("finish_reason") not in ("stop", None)
            or message.get("tool_calls")):
        return {"status": "NOT_ACCEPTED", "reason": "SUMMARY_OUTPUT_UNVERIFIED",
                "model_calls": 1}
    return {"status": "LIVE_PUBLIC_TEXT_ANSWER",
            "model_calls": 1, "latency_ms": latency_ms,
            "answer_chars": len(answer),
            "execution_binding": binding, "private_owner_records_read": 0}


def public_chat_probe_bounded():
    """Restrict Keychain and remote-call hangs to a disposable child process."""
    owner_live_source()
    _cfg, _settings, root = installed_config()
    insist(configure_strata(root, port=18080, expand_text_roles=True)
           in ("ALREADY_TEXT_ENABLED", "ALREADY_CONFIGURED"),
           "STRATA_CHAT_CONFIG_NOT_ENABLED")
    allowed_env = ("HOME", "PATH", "USER", "TMPDIR", "LANG", "LC_ALL")
    env = {key: os.environ[key] for key in allowed_env if key in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        child = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts/m1_strata_text_owner_activation.py"),
             "--public-chat-probe-child"],
            env=env, cwd=ROOT, text=True, capture_output=True,
            timeout=110, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "BLOCKED", "reason": "KEYCHAIN_OR_MODEL_TIMEOUT",
                "model_calls": "UNCERTAIN"}
    try:
        result = json.loads(child.stdout)
    except (ValueError, TypeError):
        return {"status": "BLOCKED", "reason": "CHILD_RECEIPT_UNVERIFIED",
                "model_calls": "UNCERTAIN"}
    allowed_status = {"LIVE_PUBLIC_TEXT_ANSWER", "BLOCKED", "NOT_ACCEPTED"}
    allowed_reasons = {
        "OWNER_KEYCHAIN_UNAVAILABLE", "PINNED_REMOTE_CHAT_UNAVAILABLE",
        "DISCOVERY_RUNTIME_UNAVAILABLE", "DISCOVERY_HTTP_401",
        "DISCOVERY_HTTP_403", "DISCOVERY_HTTP_429", "DISCOVERY_HTTP_500",
        "DISCOVERY_HTTP_502", "DISCOVERY_HTTP_503", "DISCOVERY_HTTP_504",
        "DISCOVERY_NO_AUTHORIZED_MODEL", "DISCOVERY_URLError",
        "DISCOVERY_TimeoutError", "DISCOVERY_JSONDecodeError",
        "REMOTE_CHAT_EXECUTION_UNVERIFIED", "SUMMARY_OUTPUT_UNVERIFIED",
    }
    if (type(result) is not dict or result.get("status") not in allowed_status
            or type(result.get("model_calls")) is not int
            or result["model_calls"] not in (0, 1, 2)
            or child.returncode not in (0, 2)):
        return {"status": "BLOCKED", "reason": "CHILD_RECEIPT_UNVERIFIED",
                "model_calls": "UNCERTAIN"}
    extra = {}
    if "offline_fallback" in result:
        allowed_offline = {
            "M1_LIVE_ANSWER", "M1_NO_ONLINE_CHAT", "M1_RESOURCE_DEFERRED",
            "M1_EXECUTION_UNVERIFIED", "M1_REPLY_UNVERIFIED",
            "M1_DISCOVERY_UNVERIFIED", "M1_UNSUPPORTED_EXECUTION",
            "PRIVACY_ROUTE_UNVERIFIED", "FALLBACK_ROUTE_UNVERIFIED",
        }
        if (result["offline_fallback"] not in allowed_offline
                or type(result.get("m1_model_calls")) is not int
                or result["m1_model_calls"] not in (0, 1)
                or result.get("private_route") not in (
                    "M1_ONLY_CONFIRMED", "REMOTE_DENIED_M1_UNAVAILABLE",
                    "REMOTE_ROUTE_DETECTED", "UNVERIFIED")
                or result.get("offline_mode") != "REMOTE_EXCLUDED"):
            return {"status": "BLOCKED", "reason": "CHILD_RECEIPT_UNVERIFIED",
                    "model_calls": "UNCERTAIN"}
        extra = {key: result[key] for key in (
            "offline_fallback", "m1_model_calls", "private_route",
            "offline_mode")}
    if "ollama_residency" in result:
        allowed_residency = {
            "EMPTY", "PINNED_9B_ONLY", "MIXED_WITH_PINNED_9B",
            "OTHER_RESIDENT", "UNVERIFIED"}
        if (type(result["ollama_residency"]) is not str
                or result["ollama_residency"] not in allowed_residency):
            return {"status": "BLOCKED", "reason": "CHILD_RECEIPT_UNVERIFIED",
                    "model_calls": "UNCERTAIN"}
        extra["ollama_residency"] = result["ollama_residency"]
    if extra.get("private_route") == "REMOTE_ROUTE_DETECTED":
        return {"status": "BLOCKED", "reason": "PRIVATE_REMOTE_ROUTE_UNVERIFIED",
                "model_calls": result["model_calls"], **extra}
    if result["status"] != "LIVE_PUBLIC_TEXT_ANSWER":
        return {"status": result["status"],
                "reason": result.get("reason") if result.get("reason") in allowed_reasons
                          else "CHILD_RECEIPT_UNVERIFIED",
                "model_calls": result["model_calls"], **extra}
    if (child.returncode != 0 or result.get("execution_binding")
            != "local:mainpc-strata:code-agent"
            or result.get("private_owner_records_read") != 0
            or type(result.get("latency_ms")) is not int
            or not 0 <= result["latency_ms"] <= 100000
            or type(result.get("answer_chars")) is not int
            or not 8 <= result["answer_chars"] <= 2048):
        return {"status": "BLOCKED", "reason": "CHILD_RECEIPT_UNVERIFIED",
                "model_calls": result["model_calls"]}
    return {**result, **extra}


def _m1_ollama_resident_class():
    """Categorize existing shared Ollama residency without changing models.

    Host-local bounded inventory only; arbitrary model names, paths, server
    replies and expiry timestamps must never be exported in Issue receipts.
    """
    try:
        from ai_foundation.shared_ollama9b_adapter import _local_json, _OPENER
        from ai_foundation.klm_9b_handler import MODEL, MODEL_DIGEST
        rows = _local_json(_OPENER.open, "/api/ps")
        if not rows:
            return "EMPTY"
        if len(rows) > 16:
            return "OTHER_RESIDENT"
        pinned = [
            row for row in rows if row.get("name", row.get("model")) == MODEL
            and row.get("digest") == MODEL_DIGEST]
        if len(pinned) == 1 and len(rows) == 1:
            return "PINNED_9B_ONLY"
        if pinned:
            return "MIXED_WITH_PINNED_9B"
        return "OTHER_RESIDENT"
    except Exception:
        return "UNVERIFIED"


def _m1_offline_and_privacy_probe():
    """Real M1 9B-only failover; remote is excluded in routing, not stopped.

    Browser/cloud providers are unaffected. No 4B, llama-swap GGUF or other
    local LLM is a fallback candidate. Never evict resident Ollama models.
    """
    from ai_foundation.compute_routing import ComputeRouter
    from ai_foundation.local_compute_registry import LocalComputeCandidate, LocalComputeRegistry
    from ai_foundation.shared_ollama9b_adapter import (
        SharedOllama9BDiscovery, SharedOllama9BExecution,
    )
    from ai_foundation.host_compute_lease import HostComputeBusy

    def report(status, calls=0, privacy="M1_ONLY_CONFIRMED"):
        return {"offline_fallback": status, "m1_model_calls": calls,
                "private_route": privacy, "offline_mode": "REMOTE_EXCLUDED"}

    try:
        candidates = tuple(SharedOllama9BDiscovery()())
    except Exception:
        return report("M1_DISCOVERY_UNVERIFIED", privacy="UNVERIFIED")
    remote = LocalComputeCandidate(
        "local:mainpc-strata:code-agent", health="ONLINE",
        capabilities=("CHAT", "CODE"),
        model="qwen3.8-flash-next-coder-iq1_m", slot="code-agent",
        same_host=False,
    )
    router = ComputeRouter(None, LocalComputeRegistry(lambda: (remote,) + candidates))
    private = router.choose("CHAT", local_required=True, strata_first=True)
    admitted = {
        c.binding: c for c in candidates
        if (c.binding == "local:ollama-shared9b:general" and c.health == "ONLINE"
            and c.same_host is True and "CHAT" in c.capabilities)
    }
    if private.binding is not None and private.binding not in admitted:
        return report("PRIVACY_ROUTE_UNVERIFIED", privacy="REMOTE_ROUTE_DETECTED")
    fallback = router.choose(
        "CHAT", strata_first=True, exclude=("local:mainpc-strata:code-agent",))
    if fallback.binding is None:
        return report("M1_NO_ONLINE_CHAT",
                      privacy=("M1_ONLY_CONFIRMED" if private.binding else
                               "REMOTE_DENIED_M1_UNAVAILABLE"))
    if (fallback.kind != "LOCAL" or fallback.binding not in admitted
            or fallback.binding != private.binding):
        return report("FALLBACK_ROUTE_UNVERIFIED", privacy="REMOTE_ROUTE_DETECTED")
    try:
        # The shared 9B transport itself revalidates the exact model digest,
        # resident models, resource gate and existing host lease.
        answer = SharedOllama9BExecution().chat(
            "In one sentence, explain that M1 can continue if MainPC is offline.",
            model=fallback.execution_slot)
        if type(answer) is str and 8 <= len(answer) <= 2048:
            return report("M1_LIVE_ANSWER", calls=1)
        return report("M1_REPLY_UNVERIFIED", calls=1)
    except HostComputeBusy:
        return report("M1_RESOURCE_DEFERRED", calls=0)
    except Exception:
        return report("M1_EXECUTION_UNVERIFIED", calls=1)


def probe_child_main():
    try:
        result = public_chat_probe_child()
    except Exception:
        # Never print exception text, Keychain content, user data or model reply.
        result = {"status": "BLOCKED", "reason": "HOST_UNVERIFIED",
                  "model_calls": "UNCERTAIN"}
    try:
        extra = _m1_offline_and_privacy_probe()
    except Exception:
        extra = {"offline_fallback": "M1_DISCOVERY_UNVERIFIED",
                 "m1_model_calls": 0, "private_route": "UNVERIFIED",
                 "offline_mode": "REMOTE_EXCLUDED"}
    result.update(extra)
    result["ollama_residency"] = _m1_ollama_resident_class()
    if type(result.get("model_calls")) is int:
        result["model_calls"] += extra["m1_model_calls"]
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "LIVE_PUBLIC_TEXT_ANSWER" else 2


def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    token = os.environ.get("GITHUB_TOKEN")
    verify = event.get("issue", {}).get("title", "").startswith(VERIFY_PREFIX)
    number = identity(event, os.environ, verify=verify)
    suffix = "/issues/" + str(number)
    identity(event, os.environ, github(token, suffix), verify=verify)
    marker = VERIFY_MARKER if verify else MARKER
    existing = github(token, suffix + "/comments?per_page=100")
    insist(type(existing) is list and len(existing) < 100,
           "RECEIPT_WINDOW_UNVERIFIED")
    insist(not any(type(c) is dict and marker + str(number) + " -->" in c.get("body", "")
                   for c in existing), "ALREADY_ATTEMPTED")
    try:
        result = public_chat_probe_bounded() if verify else activate()
    except Exception as exc:
        # Never export paths, credentials, exception messages, model text, or
        # owner config. Fixed bounded reasons only.
        known = {
            "OWNER_M1_SESSION_REQUIRED", "PINNED_MAIN_SOURCE_REQUIRED",
            "OPERATOR_PID_NOT_BOUND", "OPERATOR_NOT_IDLE",
            "OPERATOR_PLIST_UNTRUSTED", "OPERATOR_SOURCE_UNVERIFIED",
            "OPERATOR_ENTRY_UNVERIFIED", "OPERATOR_IMPORT_PATH_CHANGED",
            "OPERATOR_PRIVACY_GATE_SOURCE_MISMATCH",
            "STRATA_EXISTING_CONFIG_REVIEW_REQUIRED",
            "STRATA_TEXT_CONFIG_WRITE_UNVERIFIED",
            "STRATA_TEXT_CONFIG_READBACK_FAILED", "OPERATOR_PID_CHANGED",
            "STRATA_CHAT_CONFIG_NOT_ENABLED",
        }
        result = {"status": "BLOCKED",
                  "reason": str(exc) if type(exc) is Denied and str(exc) in known
                            else "HOST_UNVERIFIED",
                  "model_calls": 0, "service_mutations": 0, "private_egress": False}
    body = marker + str(number) + " -->\n\n~~~json\n" + json.dumps(
        result, sort_keys=True) + "\n~~~"
    github(token, suffix + "/comments", "POST", {"body": body})
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in ("CONFIGURED_RESTART_REQUIRED",
                                    "LIVE_PUBLIC_TEXT_ANSWER") else 2

if __name__ == "__main__":
    if sys.argv[1:] == ["--public-chat-probe-child"]:
        raise SystemExit(probe_child_main())
    if len(sys.argv) != 1:
        raise SystemExit("UNSUPPORTED_MODE")
    raise SystemExit(main())
