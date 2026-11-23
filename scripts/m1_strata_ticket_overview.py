"""Read-only bounded inventory for owner Strata/M1 CODE development tickets.

No model, test, GitHub API, Work claim or owner-private record content leaves
the M1. This is a current-state aggregate, not a release/admission grant.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3

if __package__:
    from .m1_development_ticket_factory import _owner_file, _owner_manifest, _strict_json, _validate_ticket, MAX_OWNER_DEVELOPMENT_TICKETS
else:
    from m1_development_ticket_factory import _owner_file, _owner_manifest, _strict_json, _validate_ticket, MAX_OWNER_DEVELOPMENT_TICKETS

_ALLOWED = {"PLANNED", "RUNNING", "VERIFIED", "FAILED",
            "WAITING_HUMAN", "CANCELLED"}
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_FAILURES = frozenset({"LOCAL_ACCEPTANCE_NOT_VERIFIED", "RuntimeError", "ValueError",
                      "PermissionError", "TimeoutError", "SyntaxError", "OSError",
                      "KeyError", "TypeError", "ModuleNotFoundError"})


def _contract(record):
    immutable = {k: v for k, v in record.items() if k != "allow_draft_delivery"}
    return "local-guarded-acceptance:" + sha256(json.dumps(
        immutable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _scope(record):
    # Local acceptance commits can differ while the reviewed task bytes stay
    # identical. Only identity, commit and optional delivery permission differ.
    return {k: v for k, v in record.items()
            if k not in {"ticket_id", "base_sha", "allow_draft_delivery"}}


def _matches(path, checkout, digest):
    try:
        return (not path.is_symlink() and path.is_file()
                and path.resolve(strict=True).is_relative_to(checkout.resolve(strict=True))
                and path.stat().st_size <= 262144
                and sha256(path.read_bytes()).hexdigest() == digest)
    except OSError:
        return False


def summarize(root, work_db):
    root = Path(root)
    out = {"status": "UNVERIFIED", "ticket_count": 0,
           "work_states": {}, "strata_verified": 0,
           "source_mismatch": 0, "contract_mismatch": 0,
           "failed_recovered_by_equivalent_ticket": 0,
           "failed_unresolved": 0, "failure_codes": {}, "model_calls": 0}
    try:
        manifest = _strict_json(_owner_manifest(root / "development/tickets.json"))
        if (type(manifest) is not dict or set(manifest) != {"version", "tickets"}
                or manifest["version"] != 1
                or type(manifest["tickets"]) is not list
                or not 1 <= len(manifest["tickets"]) <= MAX_OWNER_DEVELOPMENT_TICKETS):
            return out
        records = manifest["tickets"]
        ids = set()
        for rec in records:
            _validate_ticket(rec)
            if rec["ticket_id"] in ids:
                return out
            ids.add(rec["ticket_id"])
        path = Path(work_db)
        if path.is_symlink() or not path.is_file():
            return out
        states, verified, mismatch, contracts = {}, 0, 0, 0
        failures, successes, codes = [], [], {}
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3) as db:
            # One coherent Work snapshot, even if another owner task completes.
            db.execute("BEGIN")
            for rec in records:
                job_id = "mcp-local-development:" + sha256(json.dumps(
                    ["macos-owner-local", rec["ticket_id"]],
                    separators=(",", ":")).encode()).hexdigest()
                row = db.execute(
                    "SELECT status,result,name FROM work_steps WHERE job_id=? AND position=0",
                    (job_id,)).fetchone()
                state = ("PLANNED" if row is None else
                         row[0] if row[0] in _ALLOWED else "UNKNOWN")
                states[state] = states.get(state, 0) + 1
                if row is not None and row[2] != _contract(rec):
                    contracts += 1
                    if state == "FAILED":
                        failures.append(None)
                    continue
                if state == "FAILED":
                    failures.append(_scope(rec))
                    code = row[1] if row[1] in _FAILURES else "OTHER"
                    codes[code] = codes.get(code, 0) + 1
                if state != "VERIFIED":
                    continue
                try:
                    receipt = json.loads(row[1])
                    if (type(receipt) is not dict
                            or receipt.get("status") != "TESTED_CHANGE"
                            or type(receipt.get("sha256")) is not str
                            or not _SHA.fullmatch(receipt["sha256"])):
                        mismatch += 1
                        continue
                    checkout = root / "development/worktrees" / rec["ticket_id"]
                    if (checkout.is_symlink()
                            or not _matches(checkout / rec["target"], checkout, receipt["sha256"])
                            or not _matches(checkout / rec["test"], checkout, rec["test_sha256"])):
                        mismatch += 1
                        continue
                    if receipt.get("execution_binding") == "local:mainpc-strata:code-agent":
                        verified += 1
                        successes.append(_scope(rec))
                except (OSError, TypeError, ValueError, KeyError):
                    mismatch += 1
        recovered = sum(scope is not None and scope in successes for scope in failures)
        out.update(status="READ_VERIFIED", ticket_count=len(records),
                   work_states=states, strata_verified=verified,
                   source_mismatch=mismatch, contract_mismatch=contracts,
                   failed_recovered_by_equivalent_ticket=recovered,
                   failed_unresolved=len(failures) - recovered, failure_codes=codes)
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, PermissionError):
        pass
    return out
