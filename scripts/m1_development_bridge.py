#!/usr/bin/env python3
"""Issue-triggered, read-only M1 development diagnostics without Desktop Commander.

GitHub is a transport and audit surface, not a source of execution authority:
the default-branch workflow, exact owner, strict request vocabulary, and host
checks must all agree.  This bridge never accepts shell commands or paths.
"""
from __future__ import annotations

import http.client
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPOSITORY = "quest7070-dev/AI-Foundation"
OWNER_LOGIN = "quest7070-debug"
API_ROOT = "https://api.github.com"
REQUEST_PATTERN = re.compile(
    r"\s*<!-- foundation-m1-bridge: (\{[^\r\n]*\}) -->\s*\Z"
)
OPERATIONS = frozenset({"snapshot", "selftest", "triage", "klm-status", "runtime-status",
                        "source-status", "verify-main", "operator-status", "storage-status", "rollout-readiness",
                         "owner-count", "release-inventory", "strata-status", "llama-swap-upgrade-audit",
                        "klm-live-readonly", "mcp-stdio", "tunnel-readiness"})
SERVICES = {
    "foundation_operator": 8766,
    "foundation_remote": 8793,
    "ollama": 11434,
    "llama_swap": 9292,
    "harness": 3081,
}
MAX_RESPONSE = 65_536


class BridgeDenied(ValueError):
    """The request or environment fails the narrow bridge contract."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BridgeDenied("BRIDGE_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def parse_request(title, body):
    if not isinstance(body, str) or len(body) > 1024:
        raise BridgeDenied("BRIDGE_INVALID_BODY")
    match = REQUEST_PATTERN.fullmatch(body)
    if match is None:
        raise BridgeDenied("BRIDGE_REQUEST_FORMAT_INVALID")
    try:
        payload = json.loads(match.group(1), object_pairs_hook=_unique_object)
    except (TypeError, json.JSONDecodeError) as exc:
        raise BridgeDenied("BRIDGE_REQUEST_JSON_INVALID") from exc
    if (not isinstance(payload, dict)
            or set(payload) != {"version", "operation"}
            or type(payload["version"]) is not int
            or payload["version"] != 1
            or type(payload["operation"]) is not str
            or payload["operation"] not in OPERATIONS):
        raise BridgeDenied("BRIDGE_OPERATION_NOT_ALLOWED")
    if title != "Foundation M1 Bridge: " + payload["operation"]:
        raise BridgeDenied("BRIDGE_TITLE_MISMATCH")
    return payload["operation"]


def _issue_identity(issue):
    return (isinstance(issue, dict)
            and type(issue.get("number")) is int
            and 0 < issue["number"] <= 2_147_483_647
            and isinstance(issue.get("user"), dict)
            and issue["user"].get("login") == OWNER_LOGIN
            and issue.get("state") == "open")


def validate_event(event):
    if (not isinstance(event, dict)
            or event.get("action") != "opened"
            or not isinstance(event.get("repository"), dict)
            or event["repository"].get("full_name") != REPOSITORY
            or not _issue_identity(event.get("issue"))):
        raise BridgeDenied("BRIDGE_EVENT_AUTHORITY_INVALID")
    issue = event["issue"]
    operation = parse_request(issue.get("title"), issue.get("body"))
    return issue["number"], operation


def validate_live_issue(event, live):
    number, operation = validate_event(event)
    issue = event["issue"]
    if (not _issue_identity(live)
            or live["number"] != number
            or live.get("title") != issue.get("title")
            or live.get("body") != issue.get("body")):
        raise BridgeDenied("BRIDGE_ISSUE_CHANGED_OR_UNAUTHORIZED")
    if parse_request(live["title"], live["body"]) != operation:
        raise BridgeDenied("BRIDGE_LIVE_REQUEST_MISMATCH")
    return number, operation


def _github_api(method, suffix, token, payload=None):
    if (not isinstance(token, str) or not token.strip()
            or not suffix.startswith("/repos/" + REPOSITORY + "/issues/")):
        raise BridgeDenied("BRIDGE_GITHUB_SCOPE_INVALID")
    url = API_ROOT + suffix
    data = None if payload is None else json.dumps(
        payload, ensure_ascii=True, separators=(",", ":")
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "foundation-m1-development-bridge",
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            raw = response.read(MAX_RESPONSE + 1)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise BridgeDenied("BRIDGE_GITHUB_UNAVAILABLE") from exc
    if len(raw) > MAX_RESPONSE:
        raise BridgeDenied("BRIDGE_GITHUB_RESPONSE_TOO_LARGE")
    try:
        return json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeDenied("BRIDGE_GITHUB_RESPONSE_INVALID") from exc


def _receipt_marker(number):
    return "<!-- foundation-m1-bridge-receipt:v1:" + str(number) + " -->"


def receipt_already_exists(comments, number):
    if not isinstance(comments, list) or len(comments) >= 100:
        raise BridgeDenied("BRIDGE_COMMENT_WINDOW_INCOMPLETE")
    marker = _receipt_marker(number)
    for comment in comments:
        if not isinstance(comment, dict) or not isinstance(comment.get("body"), str):
            raise BridgeDenied("BRIDGE_COMMENT_SCHEMA_INVALID")
        if (marker in comment["body"]
                and isinstance(comment.get("user"), dict)
                and comment["user"].get("login") == "github-actions[bot]"):
            return True
    return False


def require_m1():
    if platform.system() != "Darwin" or platform.machine() not in ("arm64", "aarch64"):
        raise BridgeDenied("BRIDGE_M1_HOST_REQUIRED")


def snapshot():
    """Bounded observation only; a listening port is NOT application health."""
    require_m1()
    root = Path(__file__).resolve().parent.parent
    free = shutil.disk_usage(root).free
    reachable = {}
    for name, port in SERVICES.items():
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                reachable[name] = True
        except OSError:
            reachable[name] = False
    return {
        "platform": "macOS/arm64",
        "python_major_minor": ".".join(map(str, sys.version_info[:2])),
        "checkout_free_gib": round(free / (1024 ** 3), 2),
        "loopback_ports_reachable": reachable,
        "note": "Port reachability alone does not prove service, model or Native E2E readiness",
    }



def _fixed_command(argv):
    """Run only caller-embedded, fixed read-only macOS diagnostic argv."""
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or len(result.stdout) > MAX_RESPONSE:
        return None
    return result.stdout


def _read_only_http_probe(port, path, *, models=False):
    """Only fixed loopback HTTP GET probes; never return response body or model names."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1.0)
    try:
        connection.request("GET", path, headers={
            "Host": "127.0.0.1", "Accept": "application/json",
        })
        response = connection.getresponse()
        result = {"http_status": response.status}
        if models and response.status == 200:
            raw = response.read(4097)
            if len(raw) > 4096:
                result["models_state"] = "response_too_large"
            else:
                try:
                    data = json.loads(raw)
                    values = data.get("models") if isinstance(data, dict) else None
                    if not isinstance(values, list):
                        result["models_state"] = "invalid_schema"
                    else:
                        result["loaded_model_count"] = min(len(values), 100)
                        # Aggregate only numeric memory metrics: never copy model names.
                        vram = sum(
                            item.get("size_vram", 0)
                            for item in values[:100]
                            if isinstance(item, dict)
                            and type(item.get("size_vram", 0)) is int
                            and 0 <= item.get("size_vram", 0) < 1 << 50
                        )
                        result["loaded_vram_gib"] = round(vram / (1024 ** 3), 2)
                except (ValueError, UnicodeError):
                    result["models_state"] = "invalid_json"
        return result
    except (OSError, TimeoutError, http.client.HTTPException):
        return {"status": "unreachable"}
    finally:
        connection.close()


def _fixed_resource_groups(raw):
    """Aggregate one bounded ps snapshot without exporting commands or paths.

    CPU percentages and RSS are hints: summed RSS can double-count shared pages
    and a single ps sample does not establish safe model admission.
    """
    if type(raw) is not str or len(raw) > MAX_RESPONSE:
        return {"state": "UNAVAILABLE"}
    totals = {}
    lines = raw.splitlines()
    if len(lines) > 1600:
        return {"state": "UNAVAILABLE"}
    for line in lines:
        fields = line.strip().split(maxsplit=2)
        if len(fields) != 3:
            continue
        try:
            cpu = float(fields[0])
            rss_kib = int(fields[1])
        except (ValueError, OverflowError):
            continue
        if not (0 <= cpu <= 25600 and cpu == cpu
                and 0 <= rss_kib < 1 << 40):
            continue
        name = Path(fields[2]).name.casefold()
        if name.startswith("runner.") or name.startswith("actions.runner"):
            group = "github_runner"
        elif name.startswith(("python", "python3")):
            group = "python"
        elif (name.startswith(("google chrome", "chromium", "brave browser",
                               "safari", "webkit", "firefox", "arc helper"))):
            group = "browser"
        elif name in ("ollama", "llama-server", "llama-swap"):
            group = "local_inference_runtime"
        elif name.startswith(("docker", "com.docker", "containerd", "qemu")):
            group = "containers"
        elif name == "windowserver":
            group = "window_server"
        else:
            group = "other"
        row = totals.setdefault(group, {"cpu_pct_sum": 0., "rss_kib_sum": 0,
                                        "process_count": 0})
        row["cpu_pct_sum"] += cpu
        row["rss_kib_sum"] += rss_kib
        row["process_count"] += 1
    return {
        "state": "OBSERVED",
        "note": "Aggregated point-in-time process CPU/RSS, not admission or unique physical RAM",
        "groups": {
            group: {
                "cpu_percent_sum": round(row["cpu_pct_sum"], 1),
                "rss_gib_sum": round(row["rss_kib_sum"] / (1024 ** 2), 2),
                "count": row["process_count"],
            }
            for group, row in sorted(totals.items(),
                                     key=lambda x: -x[1]["cpu_pct_sum"])
        },
    }


def triage():
    """Fixed, low-cost failure triage without running a user-supplied command.

    Output is intentionally metadata-only; no PID, argv, log text, or model
    names are sent to GitHub. Absence in the runner's launchctl context does
    NOT prove that a service is down in another launchd user domain.
    """
    require_m1()
    result = {
        "load_average_1m": round(os.getloadavg()[0], 2),
        "http_checks": {
            "operator_health": _read_only_http_probe(8766, "/health"),
            "ollama_version": _read_only_http_probe(11434, "/api/version"),
            "ollama_loaded": _read_only_http_probe(11434, "/api/ps", models=True),
            "llama_swap_health": _read_only_http_probe(9292, "/health"),
            "harness_health": _read_only_http_probe(3081, "/health"),
        },
        "memory": {},
        "process_counts": {},
        "launch_agents": [],
        "note": ("Runner-context bounded observation only. HTTP 404/port reachability "
                 "does not establish full service readiness. No secrets, logs, "
                 "arguments, model names, inference or host effects."),
    }
    total = _fixed_command(["/usr/sbin/sysctl", "-n", "hw.memsize"])
    if total is not None and total.strip().isdigit():
        result["memory"]["physical_gib"] = round(int(total.strip()) / (1024 ** 3), 2)
    vm = _fixed_command(["/usr/bin/vm_stat"])
    if vm:
        page_size = re.search(r"page size of (\d+) bytes", vm)
        pages = {}
        for name in ("free", "inactive", "speculative"):
            match = re.search(r"^Pages " + name + r":\s+(\d+)\.", vm, re.M)
            if match:
                pages[name] = int(match.group(1))
        if page_size and len(pages) == 3:
            result["memory"]["reclaimable_estimate_gib"] = round(
                sum(pages.values()) * int(page_size.group(1)) / (1024 ** 3), 2
            )
    swap = _fixed_command(["/usr/sbin/sysctl", "-n", "vm.swapusage"])
    if swap:
        match = re.search(r"\bused = ([0-9]+(?:\.[0-9]+)?)([MGT])\b", swap)
        if match:
            divisor = {"M": 1024, "G": 1, "T": 1 / 1024}[match.group(2)]
            result["memory"]["swap_used_gib"] = round(float(match.group(1)) / divisor, 2)
    processes = _fixed_command(["/bin/ps", "-axo", "comm="])
    if processes is not None:
        names = [line.strip().rsplit("/", 1)[-1].lower()
                 for line in processes.splitlines()]
        result["process_counts"] = {
            "ollama": names.count("ollama"),
            "llama_swap": names.count("llama-swap"),
        }
    # A single read-only ps snapshot identifies broad CPU/RSS pressure
    # classes without disclosing executable paths, arguments, PIDs or secrets.
    resource_sample = _fixed_command(
        ["/bin/ps", "-axo", "pcpu=,rss=,comm="])
    result["resource_groups"] = _fixed_resource_groups(resource_sample)
    agents = _fixed_command(["/bin/launchctl", "list"])
    if agents:
        for line in agents.splitlines():
            fields = line.split()
            if len(fields) != 3:
                continue
            pid, exit_code, label = fields
            if (re.fullmatch(r"dev\.quest7070\.ai-foundation\.[a-z0-9.-]{1,80}", label)
                    and len(result["launch_agents"]) < 20):
                result["launch_agents"].append({
                    "label": label,
                    "running_in_runner_context": pid.isdecimal(),
                    "last_exit_code": int(exit_code) if re.fullmatch(r"-?\d{1,6}", exit_code) else None,
                })
    return result


def bridge_selftest():
    """Execute only the three fixed, audited stdlib suites from main checkout."""
    require_m1()
    root = Path(__file__).resolve().parent.parent
    try:
        for pattern in ("test_m1_development_bridge.py", "test_m1_runtime_status_probe.py",
                        "test_m1_operator_status_probe.py"):
            result = subprocess.run(
                [sys.executable, "-B", "-m", "unittest", "discover",
                 "-s", "tests", "-p", pattern, "-q"],
                cwd=root, capture_output=True, text=True, timeout=35,
                check=False, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            if result.returncode:
                break
    except subprocess.TimeoutExpired:
        return {"passed": False, "reason": "BRIDGE_SELFTEST_TIMEOUT"}
    return {
        "passed": result.returncode == 0,
        "exit_code": result.returncode,
        "note": "Only fixed bridge/runtime/operator unit suites executed; output not published",
    }


def result_body(number, operation, observations, run_id):
    if type(run_id) is not str or not run_id.isdecimal() or len(run_id) > 20:
        raise BridgeDenied("BRIDGE_RUN_ID_INVALID")
    status = ("PASS" if observations.get("passed") is True else "FAIL") if operation in {"selftest", "verify-main"} else "OBSERVED"
    public = {
        "schema": 1,
        "issue": number,
        "operation": operation,
        "status": status,
        "observations": observations,
        "github_run_id": run_id,
        "scope": ("existing trusted-main Foundation CI; test/cache writes only; no production service, model or Native effects"
                  if operation == "verify-main" else
                  "host-read-only; only a GitHub Issue receipt is written; no shell, host writes, model calls or Native effects"),
    }
    return (_receipt_marker(number) + "\n"
            + "**M1 development bridge receipt**\n\n"
            + "~~~json\n" + json.dumps(public, ensure_ascii=True, sort_keys=True, indent=2)
            + "\n~~~\n"), status



def _klm_timeout_phase(stderr):
    """Only fixed phase strings from our child; discard all private stderr."""
    if isinstance(stderr, bytes):
        stderr = stderr[:4096].decode("ascii", "ignore")
    if type(stderr) is not str:
        return "UNKNOWN"
    allowed = {"OWNER_CONFIG", "TOKEN_REFRESH", "KEYCHAIN_LOAD",
               "OAUTH_REFRESH_HTTP", "INBOX_READ", "DRIVE_CHANGES_READ"}
    rows = stderr[-4096:].splitlines()
    values = [line.removeprefix("KLM_PHASE:") for line in rows
              if line.startswith("KLM_PHASE:")]
    return values[-1] if values and values[-1] in allowed else "UNKNOWN"


def bounded_klm_readonly_helper(*, run=None):
    """One fixed owner read-only process; no GitHub token or arbitrary argv."""
    import subprocess
    invoke = subprocess.run if run is None else run
    script = Path(__file__).resolve().parent / "m1_klm_live_readonly_probe.py"
    env = {k: v for k, v in os.environ.items()
           if k in {"HOME", "USER", "PATH", "TMPDIR", "LANG", "LC_ALL",
                    "PYTHONPATH", "PYTHONDONTWRITEBYTECODE"}}
    result = {"status": "BLOCKED", "phase": "UNKNOWN",
              "reason": "READONLY_HELPER_UNVERIFIED",
              "model_calls": 0, "drive_mutations": 0}
    try:
        child = invoke([sys.executable, "-B", str(script)],
                       capture_output=True, text=True, env=env, timeout=55)
        if (child.returncode != 0 or type(child.stdout) is not str
                or len(child.stdout) > 8192):
            return {**result, "phase": _klm_timeout_phase(child.stderr)}
        row = json.loads(child.stdout)
        allowed_status = {"BLOCKED", "LIVE_READONLY_APIS_VERIFIED"}
        allowed_phase = {"OWNER_CONFIG", "TOKEN_REFRESH", "KEYCHAIN_LOAD",
                         "OAUTH_REFRESH_HTTP", "INBOX_READ",
                         "DRIVE_CHANGES_READ", "COMPLETE"}
        allowed_reason = {"UNCLASSIFIED", "OWNER_BINDING_UNVERIFIED",
                          "DRIVE_AUTH_REQUIRED", "OAUTH_TRANSPORT_OR_REPLY_INVALID",
                          "OAUTH_HTTP_400", "OAUTH_HTTP_401", "OAUTH_HTTP_403",
                          "OAUTH_HTTP_429", "OAUTH_HTTP_500", "OAUTH_HTTP_502",
                          "OAUTH_HTTP_503", "OAUTH_HTTP_504",
                          "DRIVE_HTTP_400", "DRIVE_HTTP_401", "DRIVE_HTTP_403",
                          "DRIVE_HTTP_404", "DRIVE_HTTP_408", "DRIVE_HTTP_409",
                          "DRIVE_HTTP_410", "DRIVE_HTTP_429", "DRIVE_HTTP_500",
                          "DRIVE_HTTP_502", "DRIVE_HTTP_503", "DRIVE_HTTP_504"}
        if (type(row) is not dict or row.get("status") not in allowed_status
                or row.get("phase") not in allowed_phase
                or row.get("model_calls") != 0 or row.get("drive_mutations") != 0
                or (row["status"] == "BLOCKED"
                    and row.get("reason") not in allowed_reason)):
            return result
        return {k: value for k, value in row.items()
                if k in {"status", "phase", "reason", "error_type",
                         "fixed_gets", "model_calls", "drive_mutations"}
                and (k != "error_type" or value in {
                    "RuntimeError", "ValueError", "PermissionError", "OSError",
                    "KeyError", "TypeError", "HTTPError", "TimeoutError"})}
    except subprocess.TimeoutExpired as exc:
        return {**result, "reason": "READONLY_HELPER_TIMEOUT",
                "phase": _klm_timeout_phase(exc.stderr)}
    except (OSError, ValueError, TypeError):
        return result


def bounded_mcp_stdio_helper(*, run=None):
    """Fixed external stdio client -> local Operator smoke; sanitized counts only.

    Never inherit a GitHub token or arbitrary provider credentials, accept
    Issue-provided argv, create a network listener, or grant MCP write tools.
    """
    invoke = subprocess.run if run is None else run
    script = Path(__file__).resolve().parent / "m1_p4_mcp_stdio_e2e.py"
    env = {k: v for k, v in os.environ.items()
           if k in {"HOME", "USER", "PATH", "TMPDIR", "LANG", "LC_ALL",
                    "PYTHONPATH", "PYTHONDONTWRITEBYTECODE"}}
    blocked = {"status": "BLOCKED", "reason": "MCP_PROBE_UNVERIFIED",
               "transport": "owner-local-stdio", "protocol": "2026-07-28",
               "operator_http_verified": False, "readonly_tool_verified": False,
               "write_authority_denied": False, "public_remote_mcp_verified": False,
               "service_mutations": 0, "model_calls": 0, "native_dispatches": 0}
    flags = ("operator_http_verified", "readonly_tool_verified", "write_authority_denied")
    no_effects = ("service_mutations", "model_calls", "native_dispatches")
    try:
        child = invoke([sys.executable, "-B", str(script)],
                       capture_output=True, text=True, env=env, timeout=35)
        if type(child.stdout) is not str or len(child.stdout) > 4096:
            return blocked
        row = json.loads(child.stdout)
        if (type(row) is not dict
                or set(row) - set(blocked) or row.get("status") not in {"BLOCKED", "OBSERVED"}
                or row.get("transport") != "owner-local-stdio"
                or row.get("protocol") != "2026-07-28"
                or row.get("public_remote_mcp_verified") is not False
                or any(type(row.get(k)) is not bool for k in flags)
                or any(type(row.get(k)) is not int or row[k] != 0 for k in no_effects)):
            return blocked
        if row["status"] == "OBSERVED" and child.returncode == 0 and all(row[k] for k in flags):
            return {**blocked, "status": "OBSERVED", "reason": "NONE",
                    **{k: True for k in flags}}
        reasons = {"MCP_STDIO_CHILD_UNAVAILABLE", "MCP_FRAMING_UNVERIFIED",
                   "MCP_DISCOVERY_UNVERIFIED", "OPERATOR_HTTP_UNAVAILABLE",
                   "OPERATOR_AGGREGATE_UNVERIFIED", "MCP_WRITE_SCOPE_NOT_DENIED",
                   "MCP_EXTERNAL_CLIENT_UNAVAILABLE"}
        if row["status"] == "BLOCKED" and child.returncode == 1 and row.get("reason") in reasons:
            return {**blocked, "reason": row["reason"]}
        return blocked
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        return blocked


def execute(event, token, run_id):
    number, operation = validate_event(event)
    prefix = f"/repos/{REPOSITORY}/issues/{number}"
    live = _github_api("GET", prefix, token)
    validate_live_issue(event, live)
    comments = _github_api("GET", prefix + "/comments?per_page=100", token)
    if receipt_already_exists(comments, number):
        return "ALREADY_RECORDED"
    if operation == "snapshot":
        observations = snapshot()
    elif operation == "selftest":
        observations = bridge_selftest()
    elif operation == "runtime-status":
        if __package__:
            from .m1_runtime_status_probe import runtime_status
        else:
            from m1_runtime_status_probe import runtime_status
        observations = runtime_status()
    elif operation == "source-status":
        if __package__:
            from .m1_runtime_status_probe import source_status
        else:
            from m1_runtime_status_probe import source_status
        observations = source_status()
    elif operation == "storage-status":
        if __package__:
            from .m1_runtime_status_probe import storage_status
        else:
            from m1_runtime_status_probe import storage_status
        observations = storage_status()
    elif operation == "operator-status":
        if __package__:
            from .m1_operator_status_probe import operator_status
        else:
            from m1_operator_status_probe import operator_status
        observations = operator_status()
    elif operation == "rollout-readiness":
        if __package__:
            from .m1_foundation_rollout_readiness import rollout_readiness
        else:
            from m1_foundation_rollout_readiness import rollout_readiness
        observations = rollout_readiness()
    elif operation == "llama-swap-upgrade-audit":
        if __package__:
            from .m1_llama_swap_upgrade import audit
        else:
            from m1_llama_swap_upgrade import audit
        observations = audit()
    elif operation == "strata-status":
        if __package__:
            from .m1_runtime_status_probe import strata_status
        else:
            from m1_runtime_status_probe import strata_status
        observations = strata_status()
    elif operation == "owner-count":
        if __package__:
            from .m1_docker_owner_count_probe import owner_count_status
        else:
            from m1_docker_owner_count_probe import owner_count_status
        observations = owner_count_status()
    elif operation == "release-inventory":
        if __package__:
            from .m1_p4_release_inventory import release_inventory, operator_live_preflight
        else:
            from m1_p4_release_inventory import release_inventory, operator_live_preflight
        observations = release_inventory()
        # Launchd/PID/loopback readiness is not a Guard approval or release.
        if observations.get("status") == "OBSERVED":
            observations["operator_live_preflight"] = operator_live_preflight()
    elif operation == "verify-main":
        raise BridgeDenied("BRIDGE_VERIFICATION_REQUIRES_EXISTING_CI")
    elif operation == "klm-live-readonly":
        # Keychain native APIs may block without returning a Python exception.
        # Cap only our newly spawned, fixed read-only child; never signal or
        # stop Ollama, models, existing KLM worker or any shared process.
        observations = bounded_klm_readonly_helper()
    elif operation == "mcp-stdio":
        observations = bounded_mcp_stdio_helper()
    elif operation == "tunnel-readiness":
        # Fixed source/binary checks only. Never inspect Keychain, create a
        # Platform tunnel, start client polling or expose Kandev credentials.
        if __package__:
            from .m1_foundation_tunnel import readiness
        else:
            from m1_foundation_tunnel import readiness
        observations = readiness()
    elif operation == "klm-status":
        # Module test imports use scripts.*, while the trusted Actions runner
        # executes this file directly from the scripts directory.
        if __package__:
            from .m1_klm_status_probe import klm_status
        else:
            from m1_klm_status_probe import klm_status
        observations = klm_status()
    else:
        observations = triage()
    body, status = result_body(number, operation, observations, run_id)
    _github_api("POST", prefix + "/comments", token, {"body": body})
    return status


def _verification_request(event, token, source_sha, *, workflow, job):
    """Reuse exact Issue authority; CI owns test execution, not this bridge."""
    if (workflow != "Foundation CI" or job not in {"unit", "bridge-verification-receipt"}
            or type(source_sha) is not str or re.fullmatch(r"[0-9a-f]{40}", source_sha) is None):
        raise BridgeDenied("BRIDGE_VERIFICATION_CONTEXT_INVALID")
    number, operation = validate_event(event)
    if operation != "verify-main":
        raise BridgeDenied("BRIDGE_VERIFICATION_OPERATION_REQUIRED")
    prefix = f"/repos/{REPOSITORY}/issues/{number}"
    validate_live_issue(event, _github_api("GET", prefix, token))
    root = Path(__file__).resolve().parent.parent
    actual = _fixed_command(["/usr/bin/git", "-C", str(root), "rev-parse", "HEAD"])
    if actual is None or actual.strip() != source_sha:
        raise BridgeDenied("BRIDGE_VERIFICATION_CHECKOUT_MISMATCH")
    comments = _github_api("GET", prefix + "/comments?per_page=100", token)
    return number, prefix, receipt_already_exists(comments, number)


def verification_preflight(event, token, source_sha, *, workflow, job):
    if job != "unit":
        raise BridgeDenied("BRIDGE_VERIFICATION_PREFLIGHT_JOB_INVALID")
    _, _, recorded = _verification_request(event, token, source_sha, workflow=workflow, job=job)
    if recorded:
        raise BridgeDenied("BRIDGE_VERIFICATION_ALREADY_RECORDED")


def verification_receipt(event, token, run_id, source_sha, outcome, *, workflow, job):
    if job != "bridge-verification-receipt" or outcome not in {"success", "failure", "cancelled", "skipped"}:
        raise BridgeDenied("BRIDGE_VERIFICATION_RECEIPT_CONTEXT_INVALID")
    number, prefix, recorded = _verification_request(event, token, source_sha, workflow=workflow, job=job)
    if recorded:
        return "ALREADY_RECORDED"
    body, status = result_body(number, "verify-main", {
        "passed": outcome == "success", "ci_outcome": outcome,
        "source_sha": source_sha, "verification": "EXISTING_FOUNDATION_CI",
        "note": "Existing frozen CI owns tests; no test command, branch or path came from the Issue",
    }, run_id)
    _github_api("POST", prefix + "/comments", token, {"body": body})
    return status


def main():
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if repo != REPOSITORY or not event_path or not token:
        raise BridgeDenied("BRIDGE_WORKFLOW_CONTEXT_INVALID")
    require_m1()
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    args = sys.argv[1:]
    if args == ["--verification-preflight"]:
        verification_preflight(event, token, os.environ.get("GITHUB_SHA", ""),
            workflow=os.environ.get("GITHUB_WORKFLOW", ""), job=os.environ.get("GITHUB_JOB", ""))
        print("Exact verify-main request and trusted checkout validated")
        return
    if args == ["--verification-receipt"]:
        status = verification_receipt(event, token, run_id, os.environ.get("GITHUB_SHA", ""),
            os.environ.get("BRIDGE_CI_OUTCOME", ""), workflow=os.environ.get("GITHUB_WORKFLOW", ""),
            job=os.environ.get("GITHUB_JOB", ""))
    elif args:
        raise BridgeDenied("BRIDGE_CLI_MODE_INVALID")
    else:
        status = execute(event, token, run_id)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    line = f"M1 bridge: {status}. Issue receipt is authoritative; no effect was requested.\n"
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(line)
    print(line, end="")
    if status == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except (BridgeDenied, OSError, ValueError, json.JSONDecodeError) as exc:
        print("M1 bridge denied: " + (str(exc) if isinstance(exc, BridgeDenied)
              else type(exc).__name__), file=sys.stderr)
        raise SystemExit(2)

