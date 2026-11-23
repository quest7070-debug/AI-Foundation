"""Bounded projection of the existing Operator's official read-only API."""
from __future__ import annotations

import http.client
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import sqlite3
import stat
import time

if __package__:
    from .m1_development_bridge import _unique_object, require_m1
    from .m1_runtime_status_probe import _timestamp
else:
    from m1_development_bridge import _unique_object, require_m1
    from m1_runtime_status_probe import _timestamp

MAX_BODY = 262144
MAX_ROWS = 2000
STATES = frozenset({"READY", "RECOVERING", "UNCERTAIN", "WAITING_HUMAN", "RUNNING", "FAILED"})
STATUSES = frozenset({"PLANNED", "RUNNING", "WAITING_HUMAN", "FAILED", "UNCERTAIN",
                     "RECOVERING", "VERIFIED", "CANCELLED"})
FUNCTIONS = frozenset({"CHAT", "CODE", "DATA", "FILES", "SEARCH", "VISION", "PC_CONTROL"})
# These exact five labels are already emitted by the existing trusted Operator.
# No arbitrary service names, endpoints, configuration or error text leave M1.
SERVICE_NAMES = ("LOCAL COMPUTE", "PROVIDER REGISTRY", "TOOLHIVE FILES",
                 "TOOLHIVE CODE", "LONG-TERM HEALTH")


def _service_breakdown(rows):
    result = dict.fromkeys(SERVICE_NAMES, "NOT_OBSERVED")
    seen = set()
    for row in rows:
        name = row.get("name")
        if type(name) is not str or name not in result:
            continue
        if name in seen:
            result[name] = "UNKNOWN"
            continue
        seen.add(name)
        flag = row.get("ok")
        result[name] = ("READY" if flag is True else
                        "UNAVAILABLE" if flag is False else "UNKNOWN")
    return result



def _counts(rows, field, allowed):
    result = {}
    for row in rows:
        value = row.get(field)
        key = value if type(value) is str and value in allowed else "UNKNOWN"
        result[key] = result.get(key, 0) + 1
    return result


def _wiring_bit(document, field):
    development = document.get("development")
    if type(development) is not dict:
        return None
    value = development.get(field)
    return value if type(value) is bool else None


def _bounded_state_count(document, field):
    raw = document.get("state_diagnostics")
    if type(raw) is not dict:
        return None
    count = raw.get(field)
    return count if type(count) is int and 0 <= count <= MAX_ROWS else None


# Only fixed failure classes leave M1. Arbitrary Work result values, job IDs,
# descriptions and exception strings are never copied to a GitHub receipt.
_FAILURE_RESULTS = frozenset({
    "PermissionError", "RuntimeError", "ValueError", "FileNotFoundError",
    "TimeoutExpired", "TimeoutError", "OSError", "AssertionError", "KeyError",
    "TypeError", "ConnectionError", "HTTPError", "OperationalError",
    "FAILED_EFFECT", "FAILED_VERIFICATION", "DENY", "LOCAL_ONLY",
    "EFFECT_STATE_CONFLICT", "TARGET_PRECONDITION_CONFLICT",
})

def _classify_failure_results(results, *, complete):
    counts = {}
    for raw in results:
        kind = raw if type(raw) is str and raw in _FAILURE_RESULTS else "OTHER"
        counts[kind] = counts.get(kind, 0) + 1
    return {"state": "OBSERVED" if complete else "BOUNDED_PARTIAL",
            "sample_count": len(results), "failure_types": counts,
            "complete": complete}

def _failure_context(rows, *, observed_at):
    """Fixed bucket-only provenance; never export a Work name, ID or timestamp."""
    kinds = {}
    ages = {}
    for _error, pos, name, updated in rows:
        if type(pos) is int and pos == 0 and name == "intake":
            kind = "INTAKE"
        elif type(pos) is int and pos == 0 and name == "klm-readonly":
            kind = "KLM_READONLY"
        else:
            kind = "OTHER_STAGE"
        kinds[kind] = kinds.get(kind, 0) + 1
        if (type(updated) in (int, float) and 0 <= updated <= observed_at
                and observed_at - updated <= 86400 * 366):
            age = ("UNDER_1_DAY" if observed_at - updated < 86400
                   else "UNDER_7_DAYS" if observed_at - updated < 86400 * 7
                   else "OLDER_THAN_7_DAYS")
        else:
            age = "AGE_UNKNOWN"
        ages[age] = ages.get(age, 0) + 1
    return {"stage_counts": kinds, "age_counts": ages}


def _host_work_failure_summary():
    """Read ONLY existing owner-validated Work DB; never initialize or mutate."""
    try:
        from scripts.m1_operator_release_cli import _installed_config, _guard_path
        home = Path.home()
        guard_file, _ = _guard_path(home)
        config = _installed_config(home)
        root = guard_file.parent
        if root != Path(config.data_dir):
            return {"state": "UNAVAILABLE"}
        db_file = root / config.work_db
        info = db_file.lstat()
        if (db_file.is_symlink() or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid() or info.st_mode & 0o022
                or info.st_size == 0):
            return {"state": "UNAVAILABLE"}
        conn = sqlite3.connect(db_file.as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            conn.execute("PRAGMA query_only=ON")
            rows = conn.execute(
                "SELECT substr(result,1,96), position, substr(name,1,96), updated_at "
                "FROM work_steps WHERE status='FAILED' "
                "ORDER BY updated_at DESC LIMIT 101"
            ).fetchall()
        finally:
            conn.close()
        selected = rows[:100]
        return {
            **_classify_failure_results(
                [row[0] for row in selected], complete=len(rows) <= 100),
            **_failure_context(selected, observed_at=time.time()),
        }
    except (OSError, ValueError, TypeError, sqlite3.Error, KeyError, RuntimeError,
            ImportError, PermissionError):
        return {"state": "UNAVAILABLE"}


def _direct_mcp_summary(document, now):
    """Copy only authenticated installed Operator's bounded canonical Work counts.

    This describes local receipts, not an external MCP connection, current
    executable release, owner approval or private HumanModel access.
    """
    development = document.get("development")
    if (type(development) is not dict
            or development.get("source") != "CURRENT_GUARD_WORK_SNAPSHOT+M1_OWNER_RUNTIME"):
        return {"status": "UNVERIFIED"}
    code = development.get("direct_mcp_status")
    if code not in {"WORK_RECEIPTS_ONLY", "NO_WORK_RECEIPTS"} or type(code) is not str:
        return {"status": "UNVERIFIED"}
    counts = {}
    for field in ("direct_mcp_running", "direct_mcp_verified_receipts", "direct_mcp_failed"):
        value = development.get(field)
        if type(value) is not int or not 0 <= value <= 32:
            return {"status": "UNVERIFIED"}
        counts[field.removeprefix("direct_mcp_")] = value
    route = development.get("direct_mcp_last_route")
    if type(route) is not str or route not in {"UNVERIFIED", "M1", "STRATA"}:
        return {"status": "UNVERIFIED"}
    updated = development.get("direct_mcp_updated_at")
    if updated is not None and _timestamp(updated, now) is None:
        return {"status": "UNVERIFIED"}
    return {"status": code, **counts, "last_route": route,
            "updated_at_epoch": _timestamp(updated, now),
            "claim": "LOCAL_WORK_RECEIPTS_ONLY"}


def _klm_lifecycle_summary(document, now):
    row = document.get("development")
    fields = ("atoms", "missing_features", "unresolved_reviews", "relations", "failed_intake")
    if (type(row) is not dict or row.get("klm_lifecycle_state") != "OBSERVED"
            or any(type(row.get("klm_" + k)) is not int
                   or not 0 <= row["klm_" + k] <= 100000 for k in fields)):
        return {"state": "UNVERIFIED"}
    observed_at = row.get("klm_lifecycle_observed_at")
    age = row.get("klm_lifecycle_snapshot_age_seconds")
    return {"state": "OBSERVED", **{k: row["klm_" + k] for k in fields},
            "observed_at_epoch": _timestamp(observed_at, now) if type(observed_at) is int else None,
            "snapshot_age_seconds": age if type(age) is int and 0 <= age <= 30 else None}



def _klm_review_triage_summary(document):
    """Only fixed category counts with an independently consistent total."""
    row = document.get("development")
    keys = ("conflict", "revision", "qualifier", "dependency",
            "difference", "duplicate", "other")
    if type(row) is not dict or row.get("klm_lifecycle_state") != "OBSERVED":
        return {"state": "UNVERIFIED"}
    values = row.get("klm_review_triage")
    total = row.get("klm_unresolved_reviews")
    if (type(values) is not dict or set(values) != set(keys)
            or type(total) is not int or not 0 <= total <= 100000
            or any(type(values[key]) is not int or not 0 <= values[key] <= 100000
                   for key in keys)
            or sum(values.values()) != total):
        return {"state": "UNVERIFIED"}
    return {"state": "OBSERVED", "counts": {key: values[key] for key in keys}}


class _KlmOverview(HTMLParser):
    """Inspect only one fixed existing overview tile; never return page text."""
    def __init__(self):
        super().__init__()
        self.current = None
        self.tiles = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "overview-tile" in attrs.get("class", "").split():
            self.current = []

    def handle_data(self, value):
        if self.current is not None:
            self.current.append(value)

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            text = " ".join(self.current)
            if text.startswith("KLM / PROCESSING "):
                self.tiles.append(text)
            self.current = None


def _klm_overview_readback(connection):
    try:
        connection.request("GET", "/", headers={"Host": "127.0.0.1", "Accept": "text/html"})
        response = connection.getresponse()
        if response.status != 200:
            return {"state": "UNVERIFIED", "reason": "OVERVIEW_HTTP_NOT_OK"}
        raw = response.read(MAX_BODY + 1)
        if len(raw) > MAX_BODY:
            return {"state": "UNVERIFIED", "reason": "OVERVIEW_RESPONSE_TOO_LARGE"}
        parser = _KlmOverview()
        parser.feed(raw.decode("utf-8"))
        if not parser.tiles:
            return {"state": "UNVERIFIED", "reason": "OVERVIEW_TILE_NOT_FOUND"}
        if len(parser.tiles) != 1:
            return {"state": "UNVERIFIED", "reason": "OVERVIEW_TILE_AMBIGUOUS"}
        text = parser.tiles[0]
        import re
        return {"state": "OBSERVED",
                "formatted_index_read": re.search(
                    r"INDEX READ \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [A-Za-z0-9:+-]+", text) is not None,
                "snapshot_age_displayed": re.search(r"SNAPSHOT AGE (?:[0-9]|[12][0-9]|30)s\b", text) is not None}
    except TimeoutError:
        return {"state": "UNVERIFIED", "reason": "OVERVIEW_TIMEOUT"}
    except UnicodeError:
        return {"state": "UNVERIFIED", "reason": "OVERVIEW_ENCODING_INVALID"}
    except (OSError, http.client.HTTPException):
        return {"state": "UNVERIFIED", "reason": "OVERVIEW_TRANSPORT_ERROR"}
    except ValueError:
        return {"state": "UNVERIFIED", "reason": "OVERVIEW_PARSE_INVALID"}


def project_operator(document, now):
    """Never copy task text, result, notice detail, identifiers or bindings."""
    if type(document) is not dict or type(document.get("state")) is not str:
        raise ValueError("OPERATOR_SCHEMA_INVALID")
    for key in ("notices", "tasks", "providers", "routes", "services", "activity"):
        rows = document.get(key)
        if (type(rows) is not list or len(rows) > MAX_ROWS
                or any(type(row) is not dict for row in rows)):
            raise ValueError("OPERATOR_SCHEMA_INVALID")
    notices, tasks = document["notices"], document["tasks"]
    services, activity = document["services"], document["activity"]
    severity = document.get("severity_counts")
    severity = severity if (type(severity) is list and len(severity) == 5
        and all(type(n) is int and 0 <= n <= 1000000 for n in severity)) else None
    notice_times = [_timestamp(row.get("updated_at"), now) for row in notices]
    starts = [_timestamp(row.get("started_at"), now) for row in activity]
    return {
        "state": "OBSERVED", "http_status": 200,
        "operator_state": document["state"] if document["state"] in STATES else "UNKNOWN",
        "state_diagnostics": {
            "failed_work_window": _bounded_state_count(document, "failed_work_window"),
            "failed_effect_window": _bounded_state_count(document, "failed_effect_window"),
            "dismissed_failed_notices_window": _bounded_state_count(document, "dismissed_failed_notices_window"),
        },
        "severity_counts": severity,
        "notices": {"window_count": len(notices), "status_counts": _counts(notices, "status", STATUSES),
            "failed_kind_counts": _counts(
                [n for n in notices if n.get("status") == "FAILED"],
                "kind", frozenset({"work", "effect", "approval", "system"})),
            "actionable_count": sum(row.get("actionable") is True for row in notices),
            "input_required_count": sum(row.get("input_required") is True for row in notices),
            "latest_updated_at_epoch": max((n for n in notice_times if n is not None), default=None)},
        "tasks": {"window_count": len(tasks), "status_counts": _counts(tasks, "status", STATUSES)},
        "activity": {"window_count": len(activity), "function_counts": _counts(activity, "function", FUNCTIONS),
            "oldest_started_at_epoch": min((n for n in starts if n is not None), default=None)},
        "services": {"window_count": len(services),
            "reported_ok": sum(row.get("ok") is True for row in services),
            "reported_unavailable": sum(row.get("ok") is False for row in services),
            "unknown": sum(type(row.get("ok")) is not bool for row in services),
            "by_service": _service_breakdown(services)},
        # Observable approval state only. Never export action, target, run ID,
        # exact Guard nonce, source, or owner/private HumanModel evidence.
        # These counts do not grant any approval authority.
        "approval": {
            "current_guard_requests": sum(
                n.get("kind") == "approval"
                and n.get("status") == "WAITING_HUMAN"
                and type(n.get("approval_ref")) is str
                and len(n["approval_ref"]) == 64
                and all(ch in "0123456789abcdef" for ch in n["approval_ref"])
                for n in notices
            ),
            "primary_review_started": sum(
                n.get("kind") == "primary_review"
                and n.get("status") == "PRIMARY_REVIEW_STARTED"
                and n.get("level") == 2 for n in notices
            ),
            "primary_review_resolved": sum(
                n.get("kind") == "primary_review"
                and n.get("status") == "PRIMARY_REVIEW_RESOLVED"
                and n.get("level") == 2 for n in notices
            ),
            "owner_escalation_waiting": sum(
                n.get("kind") == "primary_review_escalation"
                and n.get("status") == "OWNER_REVIEW_REQUIRED"
                and n.get("level") == 4 for n in notices
            ),
        },
        # Server-observed in-process source callback wiring only; no owner
        # identity, private View content, effective read or process SHA claim.
        "runtime_wiring": {
            "humanmodel_factory_registered": _wiring_bit(document, "humanmodel_factory_registered"),
            "legacy_question_resolver_enabled": _wiring_bit(document, "legacy_question_resolver_enabled"),
            "host_question_resolver_registered": _wiring_bit(document, "host_question_resolver_registered"),
        },
        "direct_mcp": _direct_mcp_summary(document, now),
        "klm_lifecycle": _klm_lifecycle_summary(document, now),
        "klm_review_triage": _klm_review_triage_summary(document),
        "provider_window_count": len(document["providers"]),
        "route_window_count": len(document["routes"]),
        "coverage": "OPERATOR_API_WINDOW_ONLY",
        "note": "Server-reported UI state, not a complete Guard/Work inventory or authority to retry/approve. No task text, results, notice details, IDs, bindings or credentials exported.",
    }


def _host_development_catalog():
    """Inspect the actual installed stdio child; no tool execution or secrets."""
    try:
        if os.getuid() != 501 or os.geteuid() != os.getuid():
            raise PermissionError("OWNER_HOST_REQUIRED")
        import plistlib
        import subprocess
        from scripts.m1_guarded_tunnel_refresh import previous_agent
        from scripts.m1_guarded_tunnel_cutover import _request, tunnel
        agent = plistlib.loads(previous_agent())
        stage = Path(agent["ProgramArguments"][2]).parent.parent
        messages = [_request(1, "server/discover"), _request(2, "tools/list")]
        clean = {key: os.environ[key] for key in ("HOME", "USER", "PATH", "TMPDIR", "LANG")
                 if type(os.environ.get(key)) is str and os.environ[key]}
        child = subprocess.run([tunnel.PYTHON, "-B", str(stage / "scripts/m1_guarded_tunnel_stdio.py")],
                               input="\n".join(json.dumps(row) for row in messages) + "\n",
                               env=clean, capture_output=True, text=True, timeout=40, check=False)
        if child.returncode != 0 or len(child.stdout) > MAX_BODY:
            raise ValueError("CATALOG_UNVERIFIED")
        rows = [json.loads(line, object_pairs_hook=_unique_object) for line in child.stdout.splitlines()]
        if (len(rows) != 2 or any(type(row) is not dict or row.get("jsonrpc") != "2.0"
                                or type(row.get("id")) is not int for row in rows)
                or [row["id"] for row in rows] != [1, 2]):
            raise ValueError("CATALOG_UNVERIFIED")
        tools = rows[1].get("result", {}).get("tools")
        if type(tools) is not list or not 1 <= len(tools) <= 16:
            raise ValueError("CATALOG_UNVERIFIED")
        names = {row.get("name") for row in tools if type(row) is dict and type(row.get("name")) is str}
        if len(names) != len(tools):
            raise ValueError("CATALOG_UNVERIFIED")
        return {"state": "OBSERVED", "revision": stage.name, "tool_count": len(names),
                "development_request_available": "development_request" in names,
                "development_admit_available": "development_admit" in names,
                "development_continue_available": "development_continue" in names,
                "development_cycle_available": "development_cycle" in names,
                "selfdev_catalog_ready": {"development_continue", "development_cycle"} <= names,
                # A fresh LOCAL child is not the remote caller's live session.
                "remote_caller_verified": False, "model_calls": 0}
    except Exception:
        return {"state": "UNVERIFIED", "remote_caller_verified": False, "model_calls": 0}


def _host_fidelity_summary():
    """Owner-host private labels -> fixed aggregate reader, never raw review rows."""
    try:
        if os.getuid() != 501 or os.geteuid() != os.getuid():
            raise PermissionError("OWNER_HOST_REQUIRED")
        from scripts.m1_operator_release_cli import _installed_config, _guard_path
        from ai_foundation.authority_manifest import verify
        from ai_foundation.human_model_fidelity_host import evaluate_owner_private_fidelity
        config = _installed_config(Path.home())
        guard_file, _ = _guard_path(Path.home())
        root = guard_file.parent
        if root != Path(config.data_dir):
            raise PermissionError("SAME_OWNER_ROOT_REQUIRED")
        verify(root, config)
        return evaluate_owner_private_fidelity(root)
    except Exception:
        return {"status": "UNVERIFIED", "reason": "OWNER_REVIEW_HOST_UNAVAILABLE",
                "evaluated_questions": 0, "review_binding_verified": False,
                "representative_fidelity_verified": False, "execution_authority": False,
                "private_content_exported": False, "model_calls": 0, "native_effects": 0}


def operator_status(*, now=None):
    require_m1()
    current = time.time() if now is None else now
    connection = http.client.HTTPConnection("127.0.0.1", 8766, timeout=3)
    try:
        connection.request("GET", "/api/human", headers={"Host": "127.0.0.1", "Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            return {"state": "UNAVAILABLE", "http_status": response.status,
                    "reason": "OPERATOR_API_NOT_OK"}
        raw = response.read(MAX_BODY + 1)
        if len(raw) > MAX_BODY:
            return {"state": "UNAVAILABLE", "http_status": 200, "reason": "OPERATOR_RESPONSE_TOO_LARGE"}
        try:
            doc = json.loads(raw, object_pairs_hook=_unique_object)
            projected = project_operator(doc, current)
            projected["humanmodel_fidelity"] = _host_fidelity_summary()
            projected["mcp_development_catalog"] = _host_development_catalog()
            lifecycle = projected["klm_lifecycle"]
            if (lifecycle.get("observed_at_epoch") is not None
                    and lifecycle.get("snapshot_age_seconds") is not None):
                projected["klm_overview"] = _klm_overview_readback(connection)
            # Existing FAILED may be hidden by dismissed notices; classify the
            # durable Work result codes locally rather than inventing a retry.
            count = projected["state_diagnostics"]["failed_work_window"]
            if type(count) is int and count > 0:
                projected["work_failure_summary"] = _host_work_failure_summary()
            return projected
        except (ValueError, UnicodeError, TypeError):
            return {"state": "UNAVAILABLE", "http_status": 200, "reason": "OPERATOR_SCHEMA_INVALID"}
    except (OSError, TimeoutError, http.client.HTTPException):
        return {"state": "UNAVAILABLE", "reason": "OPERATOR_API_UNREACHABLE"}
    finally:
        connection.close()

