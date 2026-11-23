"""Fixed, privacy-minimized KLM status readout for the existing M1 bridge.

The GitHub Issue carries NO paths. The sole LaunchAgent plist, its owner-private
report and existing Foundation Durable Work DB are discovered from a *fixed*
service label. Never return private contents, OAuth metadata, arguments or paths.
No service change, local model request or write to Drive/SQLite is performed.
"""
from __future__ import annotations

import hashlib
import json
import os
import plistlib
import re
import sqlite3
import stat
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

LABEL = "dev.quest7070.ai-foundation.klm-drive"
MAX_PLIST = 16384
MAX_CONFIG = 65536
MAX_REPORT = 32768
MAX_AGE_SECONDS = 2400
REPORT_STATUSES = frozenset({
    "CURRENT", "RESYNC_PARTIAL", "REPLAY_PARTIAL", "RESCAN_REQUIRED",
    "NOT_DUE", "DRIVE_AUTH_REQUIRED", "HOST_BINDING_BLOCKED",
    "POLL_FAILED", "SYNC_ACTIVE_OR_RECONCILE_REQUIRED",
    "CLOCK_RECONCILE_REQUIRED",
})
POLL_ERROR_CODES = frozenset({
    "UNCLASSIFIED", "DRIVE_AUTH_REQUIRED",
    "OAUTH_TRANSPORT_OR_REPLY_INVALID", "RESYNC_REPLAY_CONTRACT_REQUIRED",
    "RESYNC_CURSOR_MISSING",
    *("OAUTH_HTTP_" + str(status) for status in
      (400, 401, 403, 429, 500, 502, 503, 504)),
    *("DRIVE_HTTP_" + str(status) for status in
      (400, 401, 403, 404, 408, 409, 410, 429, 500, 502, 503, 504)),
})
RETRY_INTENT_STATUSES = frozenset({
    "NO_INPUT", "SOURCE_VERIFIED_REQUEUED_ONE", "RECONCILE_REQUIRED",
    "MULTIPLE_RETRY_INTENTS_REVIEW_REQUIRED", "ALREADY_CLAIMED",
    "SOURCE_CHANGED", "REVIEW_REQUIRED", "ORIGINAL_NOT_FAILED", "FAILED",
})
INFERENCE_STATUSES = frozenset({
    "WAIT_DEV_IDLE", "DEFER_COMPUTE_BUSY", "KLM_RECONCILE_REQUIRED",
    "HANDLER_UNBOUND", "NO_INPUT", "ALREADY_CLAIMED",
    "READ_ONLY_VERIFIED", "FAILED", "SOURCE_CHANGED",
})
COVERAGE_STATUSES = frozenset({"COMPLETE", "PARTIAL", "UNKNOWN"})
CHANGES_STATUSES = frozenset({"COMPLETE", "PARTIAL", "RESCAN_REQUIRED"})
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
POLL_ERROR_TYPES = frozenset({
    "TimeoutError", "URLError", "HTTPError", "RefreshError", "TransportError",
    "OSError", "FileNotFoundError", "PermissionError", "OperationalError",
    "ValueError", "TypeError", "KeyError", "AttributeError", "RuntimeError",
    "JSONDecodeError", "UnicodeDecodeError", "CursorExpired",
})


class KlmProbeDenied(ValueError):
    pass


def _owned_bytes(path, maximum, *, private):
    """Read only a regular file owned by this user, without following its leaf symlink."""
    p = Path(path)
    if not p.is_absolute() or ".." in p.parts:
        raise KlmProbeDenied("INVALID_OWNER_FILE_PATH")
    fd = os.open(str(p), os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
                or (st.st_mode & (0o077 if private else 0o022))
                or st.st_size > maximum):
            raise KlmProbeDenied("UNTRUSTED_OWNER_FILE")
        with os.fdopen(os.dup(fd), "rb") as stream:
            data = stream.read(maximum + 1)
        if len(data) > maximum:
            raise KlmProbeDenied("OWNER_FILE_TOO_LARGE")
        return data, st
    finally:
        os.close(fd)


def _json_owner(path, maximum):
    raw, st = _owned_bytes(path, maximum, private=True)
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise KlmProbeDenied("OWNER_JSON_INVALID") from exc
    if type(doc) is not dict:
        raise KlmProbeDenied("OWNER_JSON_NOT_OBJECT")
    return doc, st


def _fixed_service_paths(home):
    plist = Path(home) / "Library" / "LaunchAgents" / (LABEL + ".plist")
    data, _ = _owned_bytes(plist, MAX_PLIST, private=False)
    try:
        row = plistlib.loads(data)
    except (ValueError, TypeError, OverflowError, plistlib.InvalidFileException) as exc:
        raise KlmProbeDenied("SERVICE_PLIST_INVALID") from exc
    if type(row) is not dict or row.get("Label") != LABEL:
        raise KlmProbeDenied("SERVICE_LABEL_MISMATCH")
    args = row.get("ProgramArguments")
    if (type(args) is not list or not 1 <= len(args) <= 24
            or not all(type(x) is str and len(x) <= 4096 for x in args)
            or args.count("--report") != 1 or args.count("--config") != 1):
        raise KlmProbeDenied("SERVICE_FIXED_ARGS_REQUIRED")
    def option(key):
        n = args.index(key)
        if n + 1 >= len(args):
            raise KlmProbeDenied("SERVICE_OPTION_MISSING")
        path = Path(args[n+1])
        if not path.is_absolute() or ".." in path.parts:
            raise KlmProbeDenied("SERVICE_OPTION_PATH_INVALID")
        return path
    report, config = option("--report"), option("--config")
    if report.suffix != ".json" or config.suffix != ".json":
        raise KlmProbeDenied("SERVICE_JSON_PATHS_REQUIRED")
    return report, config


def _status(value, allowed):
    return value if type(value) is str and value in allowed else "UNKNOWN"


def _count(value):
    return value if type(value) is int and 0 <= value <= 100000 else None


def _freshness(st, now):
    age = now - st.st_mtime
    if age < -30 or age > 86400 * 30:
        return {"report_fresh": False, "report_age_seconds": None}
    age = round(max(0, age))
    return {"report_fresh": age <= MAX_AGE_SECONDS, "report_age_seconds": age}




def _reported_compute_admission(report):
    """Only the last GUI-host admission verdict, sanitized and no new probing.

    A read-only bridge should not run its own process/Ollama inventory and
    mistake runner/model *presence* for active inference. Older installed KLM
    reports without this field remain UNAVAILABLE, not false idle/busy.
    """
    gate = report.get("compute_admission")
    if type(gate) is not dict:
        return {"state": "UNAVAILABLE"}
    state = _status(gate.get("state"), {"NOT_EVALUATED", "AVAILABLE", "DEFER"})
    if state == "UNKNOWN":
        return {"state": "UNAVAILABLE"}
    if state == "NOT_EVALUATED":
        return {"state": state}
    reason = _status(gate.get("reason"), {
        "AVAILABLE", "CPU_PRESSURE", "MEMORY_PRESSURE", "RESOURCE_UNKNOWN"})
    if ((state == "AVAILABLE" and reason != "AVAILABLE")
            or (state == "DEFER" and reason not in {
                "CPU_PRESSURE", "MEMORY_PRESSURE", "RESOURCE_UNKNOWN"})):
        return {"state": "UNAVAILABLE"}
    return {"state": state, "reason": reason}


def _scan_progress(db, config, report_written_at):
    """Current scope's saved scan only; disclose bounded counts and fixed reason codes.

    The report's RESYNC_PARTIAL alone cannot distinguish checkpoint progress
    from the same page failing repeatedly. Do not export folder IDs, cursors,
    raw exception strings or source content through the Issue bridge.
    """
    required = {"klm_drive_native_cycle", "klm_drive_folders",
                "klm_drive_seen", "klm_drive_scans"}
    known = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if not required.issubset(known):
        return {"state": "UNAVAILABLE"}
    owner, roots = config.get("owner_scope"), config.get("roots")
    if (type(owner) is not str or type(roots) is not list
            or not roots or len(roots) > 32
            or any(type(x) is not str for x in roots)):
        return {"state": "UNAVAILABLE"}
    key = hashlib.sha256(json.dumps(
        [owner, sorted(set(roots))], ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    row = db.execute(
        "SELECT scan_id FROM klm_drive_native_cycle WHERE scope=?", (key,)
    ).fetchone()
    if row is None:
        return {"state": "SCOPE_NOT_FOUND"}
    if row[0] is None:
        return {"state": "NO_ACTIVE_SCAN"}
    scan_id = row[0]
    counts = {"COMPLETE": 0, "PENDING": 0, "PARTIAL": 0,
              "RETRY": 0, "UNPROVEN": 0, "OTHER": 0}
    safe_reasons = {
        "REVISION_CHANGED_DURING_SCAN", "REPEATED_PAGE_CURSOR",
        "CursorExpired", "TERMINAL_PAGE_UNPROVEN",
        "FOLDER_BOUND_REACHED", "PAGE_TOO_LARGE",
        "PAGE_CONTRACT_REQUIRED"
    }
    reason_counts = {}
    for status, reason, count in db.execute(
        "SELECT status, reason, COUNT(*) FROM klm_drive_folders "
        "WHERE scan=? GROUP BY status, reason", (scan_id,)
    ):
        if type(count) is not int or count < 0 or count > 1000:
            return {"state": "UNAVAILABLE"}
        counts[status if status in counts else "OTHER"] += count
        if status in {"RETRY", "UNPROVEN", "PARTIAL"} and reason:
            code = reason if reason in safe_reasons else "OTHER_REDACTED"
            reason_counts[code] = reason_counts.get(code, 0) + count
    n = db.execute(
        "SELECT COUNT(*), COALESCE(SUM(pages),0) "
        "FROM klm_drive_folders WHERE scan=?", (scan_id,)
    ).fetchone()
    objects = db.execute(
        "SELECT COUNT(*) FROM klm_drive_seen WHERE scan=?", (scan_id,)
    ).fetchone()[0]
    created = db.execute(
        "SELECT created FROM klm_drive_scans WHERE id=?", (scan_id,)
    ).fetchone()
    age = (round(max(0, report_written_at - created[0]))
           if created and type(created[0]) in (int, float)
           and 0 <= report_written_at - created[0] <= 86400 * 31 else None)
    if (not 0 <= n[0] <= 1000 or not 0 <= n[1] <= 100000
            or not 0 <= objects <= 100000):
        return {"state": "UNAVAILABLE"}
    return {"state": "OBSERVED", "folders": n[0], "pages": n[1],
            "objects": objects, "status_counts": counts,
            "reason_counts": reason_counts, "scan_age_seconds": age}



def _lifecycle_counts(conn):
    """Sanitized independent SQLite readback: statuses and totals, never identities."""
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"work_steps", "klm_drive_intake"}.issubset(tables):
        return {"state": "UNAVAILABLE"}
    known = ("VERIFIED", "FAILED", "PLANNED", "RUNNING",
             "CANCELLED", "WAITING_HUMAN")
    work_rows = conn.execute(
        "SELECT w.status, COUNT(*) FROM klm_drive_intake i "
        "JOIN work_steps w ON i.job_id=w.job_id "
        "WHERE w.position=0 GROUP BY w.status").fetchall()
    if any(status not in known or type(count) is not int
           or not 0 <= count <= 100000 for status, count in work_rows):
        return {"state": "UNAVAILABLE"}
    work = {status: 0 for status in known}
    work.update(work_rows)
    fields = {
        "atoms": "klm_atoms",
        "features": "klm_atom_features",
        "relation_reviews": "klm_relation_reviews",
        "relations": "klm_relations",
        "placements": "klm_placement_candidates",
        "plans": "klm_plans",
        "retry_history": "klm_retry_history",
    }
    metrics = {}
    for name, table in fields.items():
        if table not in tables:
            metrics[name] = None
            continue
        count = conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
        if type(count) is not int or not 0 <= count <= 100000:
            return {"state": "UNAVAILABLE"}
        metrics[name] = count

    legacy_rows = conn.execute(
        "SELECT status, COUNT(*) FROM work_steps "
        "WHERE name='klm-legacy-source-review' "
        "AND job_id LIKE 'klm-legacy-review:%' GROUP BY status").fetchall()
    if any(status not in known or type(count) is not int
           or not 0 <= count <= 100000 for status, count in legacy_rows):
        return {"state": "UNAVAILABLE"}
    legacy = {status: 0 for status in known}
    legacy.update(legacy_rows)

    intent_rows = conn.execute(
        "SELECT status, COUNT(*) FROM work_steps "
        "WHERE name='klm-source-verified-retry' "
        "AND job_id LIKE 'klm-retry-intent:%' GROUP BY status").fetchall()
    if any(status not in known or type(count) is not int
           or not 0 <= count <= 100000 for status, count in intent_rows):
        return {"state": "UNAVAILABLE"}
    intents = {status: 0 for status in known}
    intents.update(intent_rows)
    verified_requeues = 0
    for (record,) in conn.execute(
        "SELECT result FROM work_steps "
        "WHERE name='klm-source-verified-retry' AND status='VERIFIED' "
        "LIMIT 1000"):
        if type(record) is not str or len(record) > 4096:
            continue
        try:
            value = json.loads(record)
        except (ValueError, UnicodeError):
            continue
        if type(value) is dict and value.get("result") == "SOURCE_VERIFIED_REQUEUED_ONE":
            verified_requeues += 1
    audit_rows = conn.execute(
        "SELECT status, COUNT(*) FROM work_steps "
        "WHERE name='audit-derived-receipts' "
        "AND job_id LIKE 'klm-audit:%' GROUP BY status").fetchall()
    if any(status not in known or type(count) is not int
           or not 0 <= count <= 100000 for status, count in audit_rows):
        return {"state": "UNAVAILABLE"}
    audits = {name: 0 for name in known}
    audits.update(audit_rows)
    unresolved = None
    if "klm_relation_reviews" in tables:
        from ai_foundation.klm_relation_review import unresolved_review_filter
        unresolved = conn.execute(
            "SELECT COUNT(*) FROM klm_relation_reviews r WHERE "
            + unresolved_review_filter(conn)).fetchone()[0]
        if type(unresolved) is not int or not 0 <= unresolved <= 100000:
            return {"state": "UNAVAILABLE"}
    missing_features = None
    if {"klm_atoms", "klm_atom_features"}.issubset(tables):
        missing_features = conn.execute(
            "SELECT COUNT(*) FROM klm_atoms a "
            "LEFT JOIN klm_atom_features f USING(atom_id) "
            "WHERE f.atom_id IS NULL").fetchone()[0]
        if type(missing_features) is not int or not 0 <= missing_features <= 100000:
            return {"state": "UNAVAILABLE"}
    return {"state": "OBSERVED", "work_states": work,
            "legacy_work_states": legacy, "retry_intent_states": intents,
            "verified_source_retry_intents": verified_requeues,
            "audit_work_states": audits,
            "unresolved_reviews": unresolved,
            "missing_atom_features": missing_features, **metrics}


def _durable_result(config_path, *, report_written_at):
    """Read existing KLM work receipts via SQL read-only; no raw cells leave host."""
    config, _ = _json_owner(config_path, MAX_CONFIG)
    if set(config) != {"foundation_root", "roots", "owner_scope"}:
        raise KlmProbeDenied("KLM_HOST_CONFIG_SCHEMA_INVALID")
    root = Path(config["foundation_root"])
    if not root.is_absolute() or ".." in root.parts:
        raise KlmProbeDenied("FOUNDATION_ROOT_UNVERIFIED")
    foundation, _ = _json_owner(root / "config.json", MAX_CONFIG)
    value = foundation.get("work_db")
    if type(value) is not str or not value:
        raise KlmProbeDenied("FOUNDATION_WORK_DB_MISSING")
    data_root = Path(foundation.get("data_dir", root))
    if not data_root.is_absolute():
        data_root = root / data_root
    work = Path(value)
    if not work.is_absolute():
        work = data_root / work
    if ".." in work.parts:
        raise KlmProbeDenied("WORK_DB_UNVERIFIED")
    # Mode is checked before opening SQLite. Do not create or initialize tables.
    st = work.lstat()
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
            or st.st_mode & 0o077 or st.st_size > (1 << 30)):
        raise KlmProbeDenied("WORK_DB_NOT_PRIVATE")
    uri = "file:" + quote(str(work), safe="/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=1)
    try:
        conn.execute("PRAGMA query_only=ON")
        total = conn.execute(
            "SELECT COUNT(*) FROM work_steps WHERE name='klm-readonly' "
            "AND position=0 AND status='VERIFIED'"
        ).fetchone()[0]
        if type(total) is not int or total > 1000:
            raise KlmProbeDenied("KLM_VERIFIED_WINDOW_BOUND")
        legacy_total = conn.execute(
            "SELECT COUNT(*) FROM work_steps "
            "WHERE name='klm-legacy-source-review' "
            "AND position=0 AND status='VERIFIED'").fetchone()[0]
        if type(legacy_total) is not int or legacy_total > 1000:
            raise KlmProbeDenied("KLM_LEGACY_VERIFIED_WINDOW_BOUND")
        rows = conn.execute(
            "SELECT name, result, updated_at FROM work_steps "
            "WHERE name IN ('klm-readonly','klm-legacy-source-review') "
            "AND position=0 AND status='VERIFIED' LIMIT 2000"
        ).fetchall()
        scan_progress = _scan_progress(conn, config, report_written_at)
        lifecycle = _lifecycle_counts(conn)
    finally:
        conn.close()
    verified = 0
    recent = 0
    legacy_verified = 0
    for name, result, updated_at in rows:
        if type(result) is not str or len(result) > 4096:
            continue
        try:
            record = json.loads(result)
        except (ValueError, UnicodeError):
            continue
        if type(record) is not dict:
            continue
        ref = record.get("result_ref")
        src = record.get("source_sha256")
        if (record.get("execution_authority") is False
                and type(ref) is str
                and ref.startswith("klm-atoms-sha256:")
                and HEX64.fullmatch(ref[len("klm-atoms-sha256:"):]) is not None
                and type(src) is str and HEX64.fullmatch(src) is not None):
            verified += 1
            if name == "klm-legacy-source-review":
                legacy_verified += 1
            # A historical receipt cannot validate the most recent 'CURRENT'
            # report; require the durable completion to be near that tick's
            # filesystem commit time (not untrusted source/model timestamps).
            if (type(updated_at) in (float, int)
                    and report_written_at - 240 <= updated_at <= report_written_at + 30):
                recent += 1
    return {"state": "OBSERVED", "verified_work_steps": total,
            "verified_legacy_work_steps": legacy_total,
            "validated_legacy_noeffect_receipts": legacy_verified,
            "validated_noeffect_receipts": verified,
            "validated_recent_noeffect_receipts": recent,
            "scan": scan_progress,
            "lifecycle": lifecycle}


def _launch_agent_status():
    """Fixed metadata-only launchctl observation; never return raw output."""
    argv = ["/bin/launchctl", "print", "gui/" + str(os.getuid()) + "/" + LABEL]
    try:
        result = subprocess.run(argv, capture_output=True, text=True,
                                check=False, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return {"state": "UNAVAILABLE"}
    if result.returncode != 0 or len(result.stdout) > 65536:
        return {"state": "UNAVAILABLE"}
    def observed(label, bound=100000):
        match = re.search(r"^[ \t]*" + re.escape(label) +
                          r" = ([0-9]+)(?: seconds)?[ \t]*$",
                          result.stdout, flags=re.M)
        if not match:
            return None
        number = int(match.group(1))
        return number if 0 <= number <= bound else None
    return {
        "state": "OBSERVED",
        "runs": observed("runs"),
        "interval_seconds": observed("run interval"),
        "last_exit_code": observed("last exit code", bound=65535),
    }


def _installed_source(home, *, reviewed_root=None):
    """Identify the fixed public-code generation; never grant release authority."""
    unavailable = {"state": "UNAVAILABLE"}
    try:
        home = Path(home)
        raw, _ = _owned_bytes(home / "Library/LaunchAgents" / (LABEL + ".plist"),
                              MAX_PLIST, private=False)
        row = plistlib.loads(raw)
        args = row.get("ProgramArguments")
        if (row.get("Label") != LABEL or type(args) is not list
                or not all(type(arg) is str for arg in args)):
            return unavailable
        entry = "scripts/klm_drive_host_tick.py"
        entries = [Path(arg) for arg in args if arg.endswith("/" + entry)]
        if len(entries) != 1 or not entries[0].is_absolute():
            return unavailable
        root = entries[0].parents[1]
        base = home / "Library/Application Support/AI-Foundation"
        legacy = base / "klm-drive/releases"
        stages = base / "operator-release-staging"
        revision = None
        if root.parent == legacy and re.fullmatch(r"[0-9a-f]{40}", root.name):
            kind, revision = "LEGACY_RELEASE", root.name
        elif (root.name == "candidate" and root.parent.parent == stages
                and HEX64.fullmatch(root.parent.name)):
            kind = "OPERATOR_STAGE"
        else:
            # Never inspect an arbitrary owner directory selected by plist text.
            return {"state": "UNRECOGNIZED_SOURCE_LAYOUT"}
        # Reject parent symlinks before reading fixed public source paths.
        for parent in (root, *root.parents):
            if parent.is_symlink():
                return unavailable
            if parent == home:
                break
        if kind == "OPERATOR_STAGE":
            manifest_raw, _ = _owned_bytes(root.parent / "manifest.json",
                                           2097152, private=False)
            commit = json.loads(manifest_raw).get("candidate_commit")
            if type(commit) is str and re.fullmatch(r"[0-9a-f]{40}", commit):
                revision = commit
        reviewed = Path(__file__).resolve().parents[1] if reviewed_root is None else Path(reviewed_root)
        files = {}
        for name, relative in (
            ("entry", entry),
            ("cycle", "src/ai_foundation/klm_drive_cycle.py"),
            ("auth", "src/ai_foundation/klm_drive_auth.py"),
            ("lifecycle", "src/ai_foundation/knowledge_lifecycle.py"),
        ):
            path = root / relative
            if any(parent.is_symlink() for parent in path.parents if parent != root.parent):
                return unavailable
            source, _ = _owned_bytes(path, 2097152, private=False)
            expected, _ = _owned_bytes(reviewed / relative, 2097152, private=False)
            files[name] = {"sha256": hashlib.sha256(source).hexdigest(),
                           "matches_reviewed": source == expected}
        return {"state": "OBSERVED", "layout": kind,
                "declared_revision": revision, "files": files,
                "all_match_reviewed": all(item["matches_reviewed"] for item in files.values()),
                "execution_authority": False,
                "claim": "FILES_ONLY_NOT_LOADED_PROCESS_OR_GUARD_PROOF"}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return unavailable


def klm_status(*, home=None, now=None):
    """One fixed local observation; always withhold source and credential data."""
    current = time.time() if now is None else now
    try:
        report_path, config_path = _fixed_service_paths(
            Path.home() if home is None else Path(home))
        document, st = _json_owner(report_path, MAX_REPORT)
    except (OSError, KlmProbeDenied, TypeError, KeyError) as exc:
        return {"state": "UNAVAILABLE", "reason": (
            str(exc) if isinstance(exc, KlmProbeDenied) else "KLM_OWNER_REPORT_UNAVAILABLE")}
    freshness = _freshness(st, current)
    development = document.get("development")
    if type(development) is not dict:
        development = {}
    summary = {
        "state": "OBSERVED",
        **freshness,
        "launch_agent": _launch_agent_status(),
        "installed_source": _installed_source(Path.home() if home is None else Path(home)),
        "compute_admission": _reported_compute_admission(document),
        "drive_auth": _status(document.get("drive_auth"), {"BOUND", "UNBOUND"}),
        "status": _status(document.get("status"), REPORT_STATUSES),
        "poll_error_type": (_status(document.get("error_type"), POLL_ERROR_TYPES)
                            if document.get("status") == "POLL_FAILED" else None),
        "poll_error_code": (_status(document.get("poll_error_code"), POLL_ERROR_CODES)
                            if document.get("status") == "POLL_FAILED" else None),
        "coverage": _status(document.get("coverage"), COVERAGE_STATUSES),
        "changes": _status(document.get("changes"), CHANGES_STATUSES),
        "inference": _status(document.get("inference"), INFERENCE_STATUSES),
        "legacy_inference": _status(document.get("legacy_inference"), INFERENCE_STATUSES),
        "retry_intent": _status(document.get("retry_intent"), RETRY_INTENT_STATUSES),
        "folders": _count(document.get("folders")),
        "objects": _count(document.get("objects")),
        "pages": _count(document.get("pages")),
        "staged": _count(document.get("staged")),
        "duplicates": _count(document.get("duplicates")),
        "inbox_writes": _count(document.get("inbox_writes")),
        "development": {
            "complete": development.get("complete") if type(development.get("complete")) is bool else None,
            "approved_pending": _count(development.get("approved_pending")),
            "active_or_uncertain": _count(development.get("active_or_uncertain")),
            "native_only_approved": _count(development.get("native_only_approved")),
        },
        "note": ("Runner-owned private report snapshot, NOT proof of service source HEAD, "
                 "lease availability, server-side cancellation or multi-cycle E2E. "
                 "Raw source, model text, OAuth, paths and operator arguments omitted."),
    }
    try:
        summary["durable"] = _durable_result(config_path, report_written_at=st.st_mtime)
    except KlmProbeDenied as exc:
        # These codes are fixed literals owned by this module, never source text.
        summary["durable"] = {"state": "UNAVAILABLE", "reason": str(exc)}
    except (OSError, sqlite3.Error, TypeError, KeyError):
        summary["durable"] = {"state": "UNAVAILABLE", "reason": "WORK_QUERY_UNAVAILABLE"}
    # Report alone is not an authority to claim E2E. Require a fresh report,
    # explicitly successful inference and independently validated Work receipt.
    complete_receipt = (summary["report_fresh"]
        and summary["status"] == "CURRENT"
        and (summary["inference"] == "READ_ONLY_VERIFIED"
             or summary["legacy_inference"] == "READ_ONLY_VERIFIED")
        and summary["durable"].get("validated_recent_noeffect_receipts", 0) >= 1)
    summary["one_noeffect_job_evidenced"] = bool(complete_receipt)
    return summary

