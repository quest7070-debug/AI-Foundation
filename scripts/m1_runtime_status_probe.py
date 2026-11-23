"""Fixed runtime diagnosis. No raw logs, argv, paths, task IDs or model calls."""
from __future__ import annotations

import fcntl
import http.client
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import plistlib
import pwd
import re
import stat
import time

if __package__:
    from .m1_klm_status_probe import _owned_bytes, KlmProbeDenied
    from .m1_development_bridge import _fixed_command, _read_only_http_probe, require_m1
else:
    from m1_klm_status_probe import _owned_bytes, KlmProbeDenied
    from m1_development_bridge import _fixed_command, _read_only_http_probe, require_m1

AUTODEV = "dev.quest7070.ai-foundation.local9b-autodev"
LABELS = (AUTODEV, "dev.quest7070.ai-foundation.operator",
          "dev.quest7070.ai-foundation.llama-swap", "homebrew.mxcl.ollama")
STATES = frozenset({"DRAFT_PR_PRESENTED", "TESTED_CHANGE", "STOPPED",
    "INVALID_PROPOSAL", "NO_PROGRESS", "WRITE_NOT_VERIFIED",
    "WRITE_READBACK_MISMATCH", "SOURCE_CHANGED_DURING_TEST",
    "DELIVERY_UNVERIFIED", "REPAIR_BUDGET_EXHAUSTED"})
ERROR_TYPES = frozenset({"TimeoutExpired", "RuntimeError", "ValueError",
    "SyntaxError", "CalledProcessError", "PermissionError", "OSError",
    "FileNotFoundError", "KeyError", "TypeError"})
ERROR_CODES = frozenset({"MODEL_TURN_TIMEOUT", "COMPETING_WORK", "SHARED_MODEL_BUSY",
    "EXISTING_STORE_MISSING", "MODEL_IDENTITY_MISMATCH", "BACKEND_START_FAILED",
    "BASELINE_ALREADY_PASSES", "MODEL_BUDGET_PATCH_DRIFT", "HARNESS_REPLY_TOO_LARGE",
    "HARNESS_PUBLIC_TEXT_REQUIRED", "HARNESS_SOURCE_IS_ONLY_A_LITERAL",
    "SHARED_MODEL_STATE_UNKNOWN", "SHARED_MODEL_RESIDENT",
    "LOCAL_BACKEND_PORT_OCCUPIED", "CPU_PRESSURE",
    "MEMORY_PRESSURE", "RESOURCE_UNKNOWN",
    "DRAFT_CREATION_UNCERTAIN", "REMOTE_PUSH_UNCERTAIN",
    "LOCAL_COMMIT_UNCERTAIN"})
TASK = re.compile(r"(?:issue-[1-9][0-9]*-[a-f0-9]{16}|[a-z0-9][a-z0-9-]{0,120})\Z")
ISSUE_ATTEMPT = re.compile(r"issue-([1-9][0-9]*)-[a-f0-9]{16}\Z")
PUBLICATION = re.compile(r"candidate-autodev-issue-[1-9][0-9]*-[a-f0-9]{16}\.json\Z")
# Produced by the existing local9b_failed_run_intake, not a second classifier.
FAILURE_CLASSES = frozenset({"GENERATED_SOURCE_SYNTAX_ERROR", "PROPOSAL_SYNTAX_ERROR",
    "PINNED_TEST_FAILED", "NO_PROGRESS", "INVALID_PROPOSAL", "UNCLASSIFIED_FAILURE"})


def _safe_path(path):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or path.is_symlink():
        raise KlmProbeDenied("UNTRUSTED_PATH")
    # The installed M1 moves owner directories through host-managed aliases.
    # Canonicalize parent aliases; still reject leaf links and validate the
    # resolved regular file's owner/mode with _owned_bytes before reading.
    return path.resolve(strict=True)


def _json(path):
    raw, info = _owned_bytes(_safe_path(path), 32768, private=False)
    value = json.loads(raw)
    if type(value) is not dict:
        raise ValueError("INVALID_OBJECT")
    return value, info


def _intake_failure_type(row):
    """Expose the worker's fixed exception class, never its command or error text."""
    if row.get("status") != "BLOCKED":
        return None
    reason = row.get("reason")
    allowed = ERROR_TYPES | {"JSONDecodeError", "AttributeError", "TimeoutError"}
    return reason if type(reason) is str and reason in allowed else "UNKNOWN"


def _timestamp(value, now):
    return round(value, 3) if (type(value) in (int, float) and math.isfinite(value)
        and 0 < value <= now + 30) else None


def _diagnostic(row, status):
    detail = row.get("detail")
    code = detail if type(detail) is str and detail in ERROR_CODES else "UNKNOWN"
    match = re.match(r"HARNESS_EXIT_(-?[0-9]{1,5}):", detail) if type(detail) is str else None
    error = row.get("error_type")
    output = {"status": status, "error_code": code,
        "error_type": error if type(error) is str and error in ERROR_TYPES else None,
        "harness_exit_code": int(match.group(1)) if match else None,
        "location": "HARNESS_PROCESS" if match else
            ("MODEL_TURN" if code == "MODEL_TURN_TIMEOUT" else "UNKNOWN")}
    # Older installed workers have host-emitted codes in feedback but no
    # separate classification receipt. Project only these exact anchored
    # prefixes, never traceback text, source lines or a guessed test category.
    feedback = row.get("feedback")
    if code == "UNKNOWN" and type(feedback) is str and len(feedback) <= 8192:
        for prefix, location in (("GENERATED_SOURCE_SYNTAX_ERROR", "GENERATED_SOURCE_COMPILE"),
                                 ("PROPOSAL_SYNTAX_ERROR", "HARNESS_PROPOSAL")):
            if feedback.startswith(prefix + ":"):
                output.update(error_code=prefix, location=location,
                              diagnostic_source="HOST_RESULT_CODE_PREFIX")
                break
    return output


def _existing_failure_class(root, attempt, status, result):
    """Read only the existing, filename-bound no-authority diagnostic receipt."""
    match = ISSUE_ATTEMPT.fullmatch(attempt)
    if match is None:
        return None
    feedback = result.get("feedback") or ""
    if type(feedback) is not str or len(feedback) > 8192:
        return None
    try:
        record, _ = _json(root / "failures" / ("autodev-" + attempt + ".json"))
        origin = record.get("origin")
        if (type(origin) is not dict
                or origin.get("schema") != "local9b-failed-attempt-candidate/v1"
                or type(origin.get("issue")) is not int
                or origin["issue"] != int(match.group(1))
                or origin.get("attempt") != attempt
                or origin.get("result_status") != status
                or origin.get("feedback_sha256") != sha256(feedback.encode("utf-8")).hexdigest()
                or origin.get("approval_reusable") is not False):
            return None
        value = origin.get("failure_class")
        return value if type(value) is str and value in FAILURE_CLASSES else None
    except (OSError, ValueError, TypeError):
        return None


def _domain_status(label, domain):
    raw = _fixed_command(["/bin/launchctl", "print", domain + "/" + label])
    if raw is None:
        return {"observation": "UNAVAILABLE_OR_NOT_REGISTERED"}
    def number(key, signed=False):
        match = re.search(r"^[ \t]*" + re.escape(key) +
            r" = (" + (r"-?" if signed else "") + r"[0-9]{1,10})(?: seconds)?[ \t]*$", raw, re.M)
        return int(match.group(1)) if match else None
    match = re.search(r"^[ \t]*state = ([a-z ]{1,32})[ \t]*$", raw, re.M)
    state = match.group(1).strip() if match else "unknown"
    if state not in {"running", "waiting", "not running", "spawn scheduled", "exited"}:
        state = "unknown"
    pid = number("pid")
    return {"observation": "REGISTERED", "launchd_state": state,
            "process_present": pid is not None and pid > 0,
            "runs": number("runs"), "last_exit_code": number("last exit code", True),
            "interval_seconds": number("run interval")}


def lease_status(home):
    """Inspect existing flock with a transient shared nonblocking lock; never create."""
    path = Path(home) / "Library/Application Support/AI-Foundation/host-compute/compute.lock"
    fd = None
    stage = "LEASE_PATH"
    try:
        path = _safe_path(path)
        stage = "LEASE_DIRECTORY_PERMISSIONS"
        # Match HostComputeLease._open: the lock directory is private; the
        # application parent is not required to be mode 0700.
        info = path.parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise ValueError("UNTRUSTED_LEASE_DIRECTORY")
        stage = "LEASE_FILE"
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise ValueError("UNTRUSTED_LEASE")
        stage = "LEASE_LOCK_PROBE"
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"state": "EXCLUSIVE_HELD_AT_PROBE"}
        return {"state": "AVAILABLE_AT_PROBE", "note": "Not admission or proof of model idleness"}
    except (OSError, ValueError):
        return {"state": "UNAVAILABLE", "reason": stage}
    finally:
        if fd is not None:
            os.close(fd)


def _worker_identity(home):
    """Validate the installed worker script and return its launchd metadata.

    Source inventory and queue diagnostics share this owner-validated binding.
    """
    path = _safe_path(Path(home) / "Library/LaunchAgents" / (AUTODEV + ".plist"))
    raw, _ = _owned_bytes(path, 16384, private=False)
    row = plistlib.loads(raw)
    if type(row) is not dict or row.get("Label") != AUTODEV:
        raise ValueError("INVALID_LABEL")
    args = row.get("ProgramArguments")
    if (type(args) is not list or not 1 <= len(args) <= 24
            or any(type(a) is not str or len(a) > 4096
                   or any(ord(c) < 32 or ord(c) == 127 for c in a)
                   for a in args)):
        raise ValueError("INVALID_ARGS")
    workers = [Path(a) for a in args if Path(a).is_absolute() and Path(a).suffix == ".py"]
    if len(workers) != 1:
        raise ValueError("WORKER_BINDING_UNKNOWN")
    worker = _safe_path(workers[0])
    _owned_bytes(worker, 65536, private=False)
    return worker, row


def _worker_path(home):
    return _worker_identity(home)[0]


def _worker_root(home):
    worker, row = _worker_identity(home)
    env = row.get("EnvironmentVariables", {})
    if type(env) is not dict:
        raise ValueError("UNTRUSTED_STATE_ROOT")
    key = "AI_FOUNDATION_LOCAL9B_STATE_ROOT"
    if key not in env:
        return worker.parent
    value = env[key]
    if (type(value) is not str or not value or len(value) > 4096
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or not Path(value).is_absolute()):
        raise ValueError("UNTRUSTED_STATE_ROOT")
    state_root = _safe_path(Path(value))
    info = state_root.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o022):
        raise ValueError("UNTRUSTED_STATE_ROOT")
    return state_root


def autodev_status(home, now, domains):
    """Project existing intake/results only; never run/import the installed worker."""
    stage = "WORKER_BINDING"
    try:
        root = _worker_root(home)
        stage = "RESULT_DIRECTORY"
        results = _safe_path(root / "results")
        info = results.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o022):
            raise ValueError("UNTRUSTED_RESULTS")
        # Bound the directory scan; an incomplete window never claims empty/idle.
        entries = []
        with os.scandir(results) as scan:
            for entry in scan:
                entries.append(entry)
                if len(entries) > 2000:
                    return {"state": "UNAVAILABLE", "reason": "RESULT_WINDOW_EXCEEDED"}
        counts = {}
        latest = success = failure = started_at = None
        completed = set()
        started = set()
        claimed = set()
        publication_count = 0
        invalid = 0
        diagnostic = last_failure = None
        error_counts = {}
        for entry in entries:
            path = Path(entry.path)
            if PUBLICATION.fullmatch(path.name):
                publication_count += 1
                continue
            claim = re.fullmatch(r"issue-([1-9][0-9]*)\.claimed", path.name)
            if claim is not None:
                try:
                    raw, _ = _owned_bytes(_safe_path(path), 128, private=False)
                    name = raw.decode("utf-8").strip()
                    target = ISSUE_ATTEMPT.fullmatch(name[:-5]) if name.endswith(".json") else None
                    if target is None or target.group(1) != claim.group(1):
                        raise ValueError("CLAIM_IDENTITY_INVALID")
                    claimed.add(name[:-5])
                except (OSError, ValueError, TypeError):
                    invalid += 1
                continue
            if path.suffix not in {".json", ".started"} or not TASK.fullmatch(path.stem):
                continue
            try:
                if path.suffix == ".started":
                    raw, info = _owned_bytes(_safe_path(path), 128, private=False)
                    started.add(path.stem)
                    stamp = _timestamp(info.st_mtime, now)
                    started_at = max(started_at or 0, stamp or 0) or None
                    continue
                row, info = _json(path)
                completed.add(path.stem)
                status = row.get("status")
                status = status if type(status) is str and status in STATES else "UNKNOWN"
                counts[status] = counts.get(status, 0) + 1
                details = _diagnostic(row, status)
                failed = status not in {"DRAFT_PR_PRESENTED", "TESTED_CHANGE", "UNKNOWN"}
                if failed:
                    failure_class = _existing_failure_class(root, path.stem, status, row)
                    if failure_class is not None:
                        details["failure_class"] = failure_class
                        details["diagnostic_source"] = "EXISTING_FAILURE_CANDIDATE"
                        details["error_code"] = failure_class
                        details["location"] = {
                            "GENERATED_SOURCE_SYNTAX_ERROR": "GENERATED_SOURCE_COMPILE",
                            "PROPOSAL_SYNTAX_ERROR": "HARNESS_PROPOSAL",
                            "PINNED_TEST_FAILED": "FIXED_ACCEPTANCE_TEST",
                        }.get(failure_class, "DEVELOPMENT_LOOP")
                    elif details["error_code"] == "UNKNOWN":
                        details["error_code"] = status
                    code = details["error_code"]
                    error_counts[code] = error_counts.get(code, 0) + 1
                stamp = _timestamp(info.st_mtime, now)
                if stamp is not None:
                    if status == "DRAFT_PR_PRESENTED":
                        success = max(success or 0, stamp)
                    elif failed and stamp >= (failure or 0):
                        failure = stamp
                        last_failure = details
                    if latest is None or stamp > latest:
                        latest = stamp
                        diagnostic = details
            except (OSError, ValueError, TypeError):
                invalid += 1
        unfinished = len(started - completed)
        claim_only = len(claimed - started - completed)
        running = any(d.get("process_present") is True for d in domains.values())
        state = ("RUNNING" if running else "RECONCILE_REQUIRED" if unfinished or claim_only else
                 "LAST_EXIT_NONZERO" if any(d.get("observation") == "REGISTERED" and
                    d.get("last_exit_code") not in (None, 0) for d in domains.values()) else
                 "SCHEDULED_IDLE" if any(d.get("observation") == "REGISTERED" and
                    d.get("last_exit_code") == 0 for d in domains.values()) else "UNKNOWN")
        intake = {"state": "UNAVAILABLE"}
        try:
            row, info = _json(root / "intake.json")
            value = row.get("status")
            issues = row.get("issues")
            intake = {"state": value if type(value) is str and value in
                {"SUCCESS", "PARTIAL_SUCCESS", "BLOCKED"} else "UNKNOWN",
                "updated_at_epoch": _timestamp(info.st_mtime, now),
                "failure_type": _intake_failure_type(row),
                "queued_count": sum(i["status"] == "QUEUED" for i in issues)
                    if (type(issues) is list and len(issues) <= 100
                        and all(type(i) is dict and i.get("status") in {
                            "QUEUED", "HELD", "NEEDS_PRIORITY_REVIEW",
                            "ALREADY_ATTEMPTED", "NEEDS_SCOPED_CONTRACT"}
                            for i in issues)) else None}
        except (OSError, ValueError, TypeError):
            pass
        # Keep worker lifecycle separate from queue health. A pending Issue
        # is not evidence that the 9B process owns a compute lease or runs.
        # Only a recent, bounded, owner-read intake can report queued work.
        queue_state = "UNAVAILABLE"
        if state in {"RUNNING", "RECONCILE_REQUIRED"}:
            queue_state = state
        elif intake.get("state") in {"SUCCESS", "PARTIAL_SUCCESS"}:
            stamp = intake.get("updated_at_epoch")
            queued = intake.get("queued_count")
            if (type(stamp) in (float, int) and -30 <= now - stamp <= 1200
                    and type(queued) is int and queued >= 0):
                queue_state = ("NO_QUEUED_TASK" if queued == 0 else
                               "QUEUED_NOT_RUNNING" if state == "SCHEDULED_IDLE" else
                               "WORKER_EXIT_NONZERO" if state == "LAST_EXIT_NONZERO"
                               else "UNKNOWN")
        local_cycle = {"state": "UNAVAILABLE", "fresh": False}
        try:
            cycle, info = _json(root / "scheduled-code-cycle.json")
            stamp = _timestamp(info.st_mtime, now)
            value = cycle.get("state")
            if (type(value) is str and re.fullmatch(r"[A-Z0-9_]{2,96}", value)
                    and stamp is not None):
                local_cycle = {"state": value, "updated_at_epoch": stamp,
                               "fresh": -30 <= now - stamp <= 1200}
        except (OSError, ValueError, TypeError):
            pass
        # A fresh ordinary Work receipt describes the local cycle, not the
        # legacy GitHub queue's emptiness. Keep both observations separate.
        if local_cycle["fresh"] and state == "SCHEDULED_IDLE":
            # A blocked cycle (e.g. a release in flight) exits 0 and would
            # otherwise keep reporting a healthy idle queue. Surface it.
            queue_state = ("SCHEDULED_CYCLE_BLOCKED"
                           if local_cycle["state"] == "SCHEDULED_CYCLE_BLOCKED"
                           else "LOCAL_WORK_CYCLE_OBSERVED")
        # Eligible recipes: the recipe validators installed beside the
        # worker script, observed by a bounded content check only. The
        # probe never imports or runs the installed worker or recipe code.
        recipes = {"eligible": None}
        try:
            worker = _worker_path(home)
            raw, _ = _owned_bytes(
                _safe_path(worker.parent / "local9b_task_recipe.py"),
                262144, private=False)
            if b"python-fixed-test" in raw:
                recipes = {"eligible": 1}
        except (OSError, ValueError, TypeError, KlmProbeDenied):
            pass
        return {"state": state, "queue_state": queue_state, "local_cycle": local_cycle,
            "recipes": recipes,
            "result_counts": counts, "invalid_records": invalid,
            "uncompleted_start_count": unfinished, "claim_without_start_or_result_count": claim_only,
            "diagnostic_publication_records": publication_count, "last_start_at_epoch": started_at,
            "last_result_at_epoch": latest, "last_success_at_epoch": success,
            "last_failure_at_epoch": failure, "latest_result": diagnostic,
            "last_failure": last_failure, "error_code_counts": error_counts, "intake": intake,
            "note": "Timestamps are file commits; starts without results require reconciliation, not automatic retry"}
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException) as error:
        codes = {"INVALID_LABEL", "INVALID_ARGS", "WORKER_BINDING_UNKNOWN",
                 "UNTRUSTED_PATH", "UNTRUSTED_OWNER_FILE", "UNTRUSTED_RESULTS",
                  "UNTRUSTED_STATE_ROOT"}
        code = str(error) if type(error) in (ValueError, KlmProbeDenied) and str(error) in codes else (
            "OWNER_FILE_MISSING" if isinstance(error, FileNotFoundError) else
            "OWNER_PERMISSION_DENIED" if isinstance(error, PermissionError) else "OWNER_SCHEMA_UNAVAILABLE")
        return {"state": "UNAVAILABLE", "reason": stage, "code": code}


def _local_model_catalog_status():
    """Bounded loopback metadata only; never load a model or copy an alias."""
    conn = http.client.HTTPConnection("127.0.0.1", 9292, timeout=2)
    try:
        conn.request("GET", "/v1/models", headers={
            "Host": "127.0.0.1", "Accept": "application/json"})
        reply = conn.getresponse()
        if reply.status != 200:
            return {"state": "UNAVAILABLE", "reason": "CATALOG_HTTP_NON200"}
        raw = reply.read(65537)
        if len(raw) > 65536:
            return {"state": "UNAVAILABLE", "reason": "CATALOG_TOO_LARGE"}
        document = json.loads(raw)
        rows = document.get("data") if type(document) is dict else None
        if type(rows) is not list or len(rows) > 128:
            return {"state": "UNAVAILABLE", "reason": "CATALOG_SCHEMA_UNVERIFIED"}
        values = {"loaded": 0, "unloaded": 0, "loading": 0,
                  "failed": 0, "other": 0}
        for row in rows:
            if type(row) is not dict or type(row.get("id")) is not str:
                return {"state": "UNAVAILABLE", "reason": "CATALOG_SCHEMA_UNVERIFIED"}
            status = row.get("status")
            value = status.get("value") if type(status) is dict else None
            code = value.lower() if type(value) is str else ""
            values[code if code in values and code != "other" else "other"] += 1
        return {
            "state": "OBSERVED", "configured_alias_count": len(rows),
            "runtime_state_counts": values,
            "note": "Configured aliases only; no artifact/readiness/role or inference authority established.",
        }
    except (OSError, ValueError, TypeError, http.client.HTTPException):
        return {"state": "UNAVAILABLE", "reason": "CATALOG_TRANSPORT_OR_JSON"}
    finally:
        conn.close()


def _local_compute_admission_status(home):
    """Legacy llama-swap inventory only; not the active shared-9B admission."""
    try:
        from scripts.m1_operator_release_cli import _guard_path
        from ai_foundation.llama_swap_adapter import LlamaSwapDiscovery
        _, registry_path = _guard_path(home)
        manifest = registry_path.parent / "local-compute" / "llama-swap.yaml"
        candidates = LlamaSwapDiscovery(manifest_path=manifest)()
        if len(candidates) > 128:
            raise ValueError("CATALOG_TOO_LARGE")
        allowed = {
            "MODEL_ARTIFACT_MISSING", "NO_MODEL", "UNASSIGNED_ROLE",
            "RUNTIME_FAILED", "RUNTIME_ERROR", "RUNTIME_UNAVAILABLE",
            "RUNTIME_DISABLED"}
        reasons = {}
        health = {}
        routable = 0
        for row in candidates:
            key = row.health if row.health in {"ONLINE", "UNAVAILABLE"} else "OTHER"
            health[key] = health.get(key, 0) + 1
            if row.reason is not None:
                reason = row.reason if row.reason in allowed else "OTHER"
                reasons[reason] = reasons.get(reason, 0) + 1
            routable += row.health == "ONLINE" and bool(row.capabilities)
        return {"state": "OBSERVED", "candidate_count": len(candidates),
                "health_counts": health, "reason_counts": reasons,
                "routable_count": routable, "manifest_present": manifest.is_file(),
                "model_calls": 0}
    except (OSError, ValueError, TypeError, RuntimeError, ImportError, AttributeError):
        return {"state": "UNAVAILABLE", "model_calls": 0}


def _shared9b_admission_status(discover=None):
    """Observe the active M1 discovery without loading or calling a model."""
    unknown = {"state": "UNVERIFIED", "health": "UNVERIFIED",
               "reason": "SHARED_9B_STATE_UNVERIFIED", "model_calls": 0}
    try:
        if discover is None:
            from ai_foundation.shared_ollama9b_adapter import SharedOllama9BDiscovery
            discover = SharedOllama9BDiscovery()
        rows = discover()
        if (type(rows) not in (tuple, list) or len(rows) != 1
                or rows[0].binding != "local:ollama-shared9b:general"
                or rows[0].same_host is not True):
            return unknown
        row = rows[0]
        if row.health not in {"ONLINE", "UNAVAILABLE"}:
            return unknown
        reasons = {"PINNED_9B_NOT_VERIFIED", "OTHER_LOCAL_MODEL_OR_BACKEND_RESIDENT",
                   "CPU_PRESSURE", "MEMORY_PRESSURE", "RESOURCE_UNKNOWN",
                   "SHARED_9B_STATE_UNVERIFIED"}
        reason = (None if row.health == "ONLINE" and row.reason is None
                  else row.reason if type(row.reason) is str and row.reason in reasons
                  else "UNCLASSIFIED")
        return {"state": "OBSERVED", "health": row.health, "reason": reason,
                "model_calls": 0}
    except (OSError, ValueError, TypeError, RuntimeError, ImportError, AttributeError, KeyError):
        return unknown


def runtime_status(*, home=None, now=None):
    require_m1()
    # Plists use the same owner home as the accepted KLM probe. The compute
    # lease separately follows its authoritative canonical_lock_path contract.
    lease_home = Path(pwd.getpwuid(os.getuid()).pw_dir) if home is None else Path(home)
    home = Path.home() if home is None else Path(home)
    now = time.time() if now is None else now
    domains = ("gui/" + str(os.getuid()), "user/" + str(os.getuid()), "system")
    services = {label: {domain: _domain_status(label, domain) for domain in domains}
                for label in LABELS}
    raw = _fixed_command(["/bin/ps", "-axo", "comm="])
    names = [Path(n.strip()).name.lower() for n in raw.splitlines()] if raw is not None else None
    return {"services": services,
        "local_model_catalog": _local_model_catalog_status(),
        "local_compute_admission": _local_compute_admission_status(home),
        "local_compute_admission_scope": "LEGACY_LLAMA_SWAP_ONLY",
        "shared9b_admission": _shared9b_admission_status(),
        "http_contracts": {
            "operator_models_route": _read_only_http_probe(8766, "/v1/models"),
            "ollama_version": _read_only_http_probe(11434, "/api/version"),
            "llama_swap_health": _read_only_http_probe(9292, "/health")},
        "process_counts": {name: names.count(name) if names is not None else None
            for name in ("ollama", "llama-swap", "kandev", "dsh", "llama-server")},
        "autodev": autodev_status(home, now, services[AUTODEV]),
        "compute_lease": lease_status(lease_home),
        "harness": {"mode": "ON_DEMAND_CLI", "http_port_required": False,
                    "note": "CLI lifecycle evidenced by worker results; no standalone HTTP readiness inferred"},
        "kandev": {"health": "USE_EXISTING_CONTROL_MCP_STATUS", "http_health": "UNVERIFIED_CONTRACT"},
        "note": "Fixed domains are separate observations. Unavailable, no PID or HTTP 404 is not an outage verdict. No raw logs or private values exported."}


SOURCE_FILES = {
    "worker": None,
    "issue_intake": "local9b_issue_bridge.py",
    "task_selection": "local9b_task_selection.py",
    "task_recipe": "local9b_task_recipe.py",
    "failure_intake": "local9b_failed_run_intake.py",
    "failure_candidates": "local9b_failure_candidates.py",
    "development_host": "modules/ai_foundation/development_host.py",
    "development_loop": "modules/ai_foundation/development_loop.py",
    "compute_lease": "modules/ai_foundation/host_compute_lease.py",
}


def source_status(*, home=None, now=None):
    """Fingerprint only fixed installed sources selected by the existing owner plist."""
    require_m1()
    home = Path.home() if home is None else Path(home)
    now = time.time() if now is None else now
    try:
        worker = _worker_path(home)
        root = worker.parent
    except (OSError, ValueError, TypeError, KeyError, StopIteration, plistlib.InvalidFileException):
        return {"state": "UNAVAILABLE", "reason": "WORKER_SOURCE_BINDING_UNAVAILABLE"}
    files = {}
    release_package = root.parent / "src" / "ai_foundation"
    has_release_package = release_package.is_dir() and not release_package.is_symlink()
    for name, relative in SOURCE_FILES.items():
        if relative is None:
            path = worker
        elif has_release_package and relative.startswith("modules/ai_foundation/"):
            path = release_package / relative[len("modules/ai_foundation/"):]
        else:
            path = root / relative
        try:
            data, info = _owned_bytes(_safe_path(path), 262144, private=False)
            files[name] = {"state": "OBSERVED", "sha256": sha256(data).hexdigest(),
                "size_bytes": len(data), "modified_at_epoch": _timestamp(info.st_mtime, now)}
        except (OSError, ValueError, TypeError):
            files[name] = {"state": "UNAVAILABLE"}
    return {"state": "OBSERVED", "files": files,
        "note": "Installed file fingerprints only; no source text, paths, git remotes or credentials. A hash alone does not prove loaded process identity or approved deployment."}


STORAGE_LOG_LABELS = {
    "autodev": AUTODEV,
    "operator": "dev.quest7070.ai-foundation.operator",
    "llama_swap": "dev.quest7070.ai-foundation.llama-swap",
}


def _space_status(path):
    """Constant-time filesystem metadata, without scanning directories."""
    try:
        path = Path(path).resolve(strict=True)
        info, space = path.stat(), os.statvfs(path)
        block = space.f_frsize or space.f_bsize
        total = space.f_blocks * block
        available = max(0, space.f_bavail) * block
        if block <= 0 or total <= 0 or not 0 <= available <= total:
            raise ValueError("INVALID_FILESYSTEM_METRICS")
        readonly_flag = getattr(os, "ST_RDONLY", None)
        return {"state": "OBSERVED", "total_gib": round(total / 1024 ** 3, 2),
            "available_gib": round(available / 1024 ** 3, 2),
            "read_only": bool(space.f_flag & readonly_flag) if readonly_flag is not None else None}, info.st_dev
    except (OSError, ValueError):
        return {"state": "UNAVAILABLE"}, None


def _log_metadata(home, label, now):
    result = {"stdout": {"state": "UNAVAILABLE"}, "stderr": {"state": "UNAVAILABLE"}}
    try:
        path = _safe_path(Path(home) / "Library/LaunchAgents" / (label + ".plist"))
        raw, _ = _owned_bytes(path, 16384, private=False)
        doc = plistlib.loads(raw)
        if type(doc) is not dict or doc.get("Label") != label:
            return result
        for key, field in (("stdout", "StandardOutPath"), ("stderr", "StandardErrorPath")):
            value = doc.get(field)
            if type(value) is not str or len(value) > 4096:
                continue
            try:
                info = _safe_path(value).lstat()
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_mode & 0o022 or not 0 <= info.st_size <= 1 << 50):
                    continue
                result[key] = {"state": "OBSERVED", "size_bytes": info.st_size,
                               "modified_at_epoch": _timestamp(info.st_mtime, now)}
            except (OSError, ValueError):
                continue
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
        pass
    return result


def storage_status(*, home=None, now=None):
    require_m1()
    home = Path.home() if home is None else Path(home)
    current = time.time() if now is None else now
    targets = {"system": Path("/"), "owner_home": home}
    try:
        targets["installed_worker"] = _worker_root(home)
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
        targets["installed_worker"] = None
    volumes, devices = {}, {}
    for name, path in targets.items():
        value, device = _space_status(path) if path is not None else ({"state": "UNAVAILABLE"}, None)
        if device is not None:
            if device not in devices:
                devices[device] = len(devices)
            value["filesystem_group"] = devices[device]
        volumes[name] = value
    return {"state": "OBSERVED", "filesystems": volumes,
        "logs": {name: _log_metadata(home, label, current) for name, label in STORAGE_LOG_LABELS.items()},
        "note": "Filesystem capacity and fixed log stat metadata only. No directory scan, log-content read, actual paths/device IDs, deletion or permission change. Filesystem groups do not identify physical disks or APFS shared-container capacity."}


def strata_status(*, config_path=None):
    """Read owner-pinned MainPC configuration; at most fixed models discovery.

    No model inference, MainPC wake, path/key/source egress, command execution,
    or authorization to change another endpoint. A GitHub runner's missing
    environment key does NOT prove the installed Operator lacks a credential.
    """
    require_m1()
    installed_context = config_path is None
    if config_path is None:
        try:
            if __package__:
                from .m1_human_model_activation_readiness import installed_paths
            else:
                from m1_human_model_activation_readiness import installed_paths
            installed = installed_paths()
            if installed is None:
                return {"status": "OWNER_DATA_ROOT_UNAVAILABLE"}
            config_path = installed[1] / "local-compute" / "endpoints.json"
        except (OSError, ValueError, TypeError, KeyError):
            return {"status": "OWNER_DATA_ROOT_UNAVAILABLE"}
    try:
        raw, _ = _owned_bytes(_safe_path(config_path), 65536, private=True)
    except FileNotFoundError:
        return {"status": "MAINPC_CONFIG_ABSENT"}
    except (OSError, ValueError, KlmProbeDenied):
        return {"status": "MAINPC_CONFIG_UNTRUSTED"}
    try:
        doc = json.loads(raw)
        def invalid(reason):
            # Only fixed reason categories leave the M1; never raw config,
            # model names, addresses, credentials or file paths.
            return {"status": "MAINPC_CONFIG_INVALID", "reason_code": reason}
        if type(doc) is not dict or doc.get("version") != 1:
            return invalid("SCHEMA_VERSION")
        endpoints = doc.get("endpoints")
        if type(endpoints) is not list or len(endpoints) > 32:
            return invalid("ENDPOINTS_SCHEMA")
        matching = [r for r in endpoints if type(r) is dict
                    and r.get("name") == "mainpc-strata"]
        if not matching:
            return {"status": "MAINPC_STRATA_NOT_CONFIGURED"}
        if len(matching) != 1:
            return invalid("DUPLICATE_STRATA_ENDPOINT")
        row = matching[0]
        from urllib.parse import urlsplit
        url = urlsplit(row.get("base_url"))
        hosts = row.get("allowed_hosts")
        models = row.get("models")
        if (url.scheme != "http" or url.username or url.password or
                url.path not in ("", "/") or url.query or url.fragment):
            return invalid("URL_POLICY")
        if type(hosts) is not list or url.hostname not in hosts:
            return invalid("HOST_ALLOWLIST")
        # The trusted owner may have named the Strata credential differently.
        # Never read a generic provider/GitHub token from this workflow's env:
        # only Strata-scoped aliases may be used for authenticated discovery.
        credential_env = row.get("api_key_env")
        if (type(credential_env) is not str or
                re.fullmatch(r"(?:STRATA|MAINPC_STRATA)_[A-Z0-9_]{2,63}",
                             credential_env) is None):
            return invalid("KEY_BINDING")
        if row.get("optional") is not True:
            return invalid("OPTIONAL_GUARD")
        if (type(models) is not list or len(models) != 1 or
                type(models[0]) is not dict or
                models[0].get("alias") != "code-agent" or
                models[0].get("runtime_model") !=
                "qwen3.8-flash-next-coder-iq1_m" or
                "CODE" not in models[0].get("capabilities", ())):
            return invalid("CODE_MODEL_POLICY")
    except (ValueError, TypeError, KeyError, AttributeError):
        return {"status": "MAINPC_CONFIG_INVALID",
                "reason_code": "INVALID_CONFIG_VALUE"}
    if not os.environ.get(credential_env):
        report = {"status": "RUNNER_KEY_UNAVAILABLE",
                  "model_calls": 0, "note": "Owner Operator credentials not inferred"}
        # Observe only the already-reviewed direct-link address. Never probe a
        # caller-selected endpoint or send a bearer to an unauthenticated host.
        if row.get("base_url") == "http://10.0.1.1:18080":
            if __package__:
                from .mainpc_management_readiness import management_readiness
            else:
                from mainpc_management_readiness import management_readiness
            report["execution_environment"] = management_readiness()
        if installed_context:
            try:
                if __package__:
                    from .m1_direct_development import diagnose, installed_config
                else:
                    from m1_direct_development import diagnose, installed_config
                _, config, root = installed_config()
                report["direct_development"] = diagnose()
                if __package__:
                    from .m1_strata_ticket_overview import summarize
                else:
                    from m1_strata_ticket_overview import summarize
                report["direct_development"]["tickets"] = summarize(
                    root, root / config.work_db)
            except (OSError, ValueError, TypeError, KeyError, RuntimeError):
                report["direct_development"] = {"status": "DIRECT_DEVELOPMENT_UNAVAILABLE", "model_calls": 0}
        return report
    try:
        if __package__:
            from .mainpc_strata_preflight import verify_strata
        else:
            from mainpc_strata_preflight import verify_strata
        result = verify_strata(config_path, wake=False, smoke=False)
        code = result.get("status") if type(result) is dict else None
    except (OSError, ValueError, TypeError, KeyError):
        code = None
    allowed = {"MODEL_DISCOVERED", "MAINPC_UNAVAILABLE",
               "MAINPC_MODEL_NOT_BOUND", "MAINPC_STRATA_NOT_CONFIGURED",
               "CONFIG_UNAVAILABLE"}
    return {"status": code if code in allowed else "MAINPC_DISCOVERY_UNVERIFIED",
            "model_calls": 0, "wake_calls": 0}
