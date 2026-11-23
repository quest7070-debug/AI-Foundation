#!/usr/bin/env python3
"""Read-only M1/GitHub acceptance of existing ready 9B Issue contracts.

Reuses the *same* Issue contract parser and dependency admission as the
existing worker. No claim creation, no local model, no Guard or Git writes,
no Native task, no branch/PR, and no outcome inference. This verifies the
current immutable GitHub base and fixed test bytes, NOT a failing baseline,
an available compute slot, or an unconsumed local execution receipt.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import sys
from urllib.parse import quote

from dev_autonomy_intake import GitHubAPI
from local9b_issue_bridge import REPOSITORY, READY_LABEL, issue_task
from local9b_task_selection import admission
from local9b_task_recipe import validate_contract

NO_AUTH = "PINNED_READY_ISSUE_VERIFIED_NO_EXECUTION"


def _normalise_issue(value):
    if (type(value) is not dict or type(value.get("number")) is not int
            or type(value.get("updated_at")) is not str
            or value.get("state") not in ("open", "closed")
            or type(value.get("body")) is not str
            or type(value.get("labels")) is not list):
        raise ValueError("ISSUE_REST_SNAPSHOT_INVALID")
    return {
        "number": value["number"], "state": value["state"].upper(),
        "updatedAt": value["updated_at"], "body": value["body"],
        "labels": value["labels"],
    }


def _decode_blob(api, path, ref):
    if not re.fullmatch(r"(?:src/ai_foundation|tests)/[A-Za-z0-9_]+\.py", path):
        raise ValueError("ISSUE_PREFLIGHT_PATH_INVALID")
    payload = api.request(api.repo_path(
        "/contents/" + quote(path, safe="/") + "?ref=" + quote(ref, safe="")))
    if (type(payload) is not dict or payload.get("type") != "file"
            or payload.get("path") != path
            or payload.get("encoding") != "base64"
            or type(payload.get("content")) is not str):
        raise ValueError("ISSUE_PREFLIGHT_BLOB_INVALID")
    try:
        return base64.b64decode(payload["content"].replace("\n", ""), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("ISSUE_PREFLIGHT_BASE64_INVALID") from exc


def verify_ready_issue(api, number: int):
    """True read-only admission preflight; no model or local execution."""
    if type(number) is not int or number <= 0:
        raise ValueError("ISSUE_NUMBER_INVALID")

    def live():
        return _normalise_issue(api.request(api.repo_path("/issues/" + str(number))))

    original = live()
    if admission(original)["status"] != "ELIGIBLE":
        raise ValueError("ISSUE_PREFLIGHT_HELD")
    if READY_LABEL not in {tag["name"] for tag in original["labels"]}:
        raise ValueError("ISSUE_PREFLIGHT_NOT_READY")

    def dependency(dep):
        value = api.request(api.repo_path("/issues/" + str(dep)))
        if type(value) is not dict:
            raise ValueError("ISSUE_PREFLIGHT_DEPENDENCY_INVALID")
        return {"number": value.get("number"), "state": value.get("state")}

    task = issue_task(original, read_dependency=dependency)
    if task.get("recipe") != "python-fixed-test":
        raise ValueError("ISSUE_PREFLIGHT_UNSUPPORTED_RECIPE")
    validate_contract({key: task[key] for key in (
        "recipe", "base", "base_sha", "target", "test",
        "test_sha256", "instruction")})
    base = task["base"]
    if not re.fullmatch(r"(?:main|local9b/[A-Za-z0-9_./-]{1,140})", base):
        raise ValueError("ISSUE_PREFLIGHT_BASE_INVALID")
    ref_commit = api.request(api.repo_path(
        "/commits/" + quote(base, safe="")))
    if type(ref_commit) is not dict or ref_commit.get("sha") != task["base_sha"]:
        raise ValueError("ISSUE_PREFLIGHT_BASE_MOVED")
    _decode_blob(api, task["target"], task["base_sha"])
    test_content = _decode_blob(api, task["test"], task["base_sha"])
    if hashlib.sha256(test_content).hexdigest() != task["test_sha256"]:
        raise ValueError("ISSUE_PREFLIGHT_TEST_SHA_DRIFT")

    # A label, body or dependency update during the network read revokes this
    # snapshot. The worker will still perform its own fresh intake before use.
    refreshed = live()
    if (refreshed != original
            or admission(refreshed)["status"] != "ELIGIBLE"
            or issue_task(refreshed, read_dependency=dependency) != task):
        raise ValueError("ISSUE_PREFLIGHT_REVISION_CHANGED")
    return {
        "issue": number, "status": NO_AUTH, "base_sha": task["base_sha"],
        "source": task["target"], "test": task["test"],
        "test_sha256": task["test_sha256"],
        "model_invoked": False, "baseline_reproduced": False,
        "compute_lease_checked": False, "already_attempted_checked": False,
        "execution_authorized_by_preflight": False,
    }


def verify_held_issue(api, number: int):
    """Receipt-free execution quarantine for independently consumed old work.

    This proves the live Issue is held, not where previous model results live.
    Never removes an at-most-once claim or reactivates old work.
    """
    if type(number) is not int or number < 1:
        raise ValueError("ISSUE_NUMBER_INVALID")
    def read():
        return _normalise_issue(api.request(api.repo_path("/issues/" + str(number))))
    first = read()
    labels = {tag["name"] for tag in first["labels"]
              if type(tag) is dict and type(tag.get("name")) is str}
    if (first["state"] != "OPEN" or "foundation-autodev:hold" not in labels
            or admission(first)["status"] != "HELD"):
        raise ValueError("ISSUE_EXPECTED_HOLD_MISSING")
    if read() != first:
        raise ValueError("ISSUE_HOLD_SNAPSHOT_MOVED")
    return {"issue": number, "status": "EXPLICITLY_HELD_NOT_EXECUTABLE",
            "model_invoked": False, "execution_authorized_by_preflight": False}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue", type=int, action="append", default=[])
    parser.add_argument("--expect-held", type=int, action="append", default=[])
    args = parser.parse_args(argv)
    if not args.issue and not args.expect_held:
        parser.error("provide at least one Issue to verify")
    if set(args.issue) & set(args.expect_held):
        parser.error("cannot expect a single Issue to be both ready and held")
    try:
        api = GitHubAPI(os.environ.get("GITHUB_TOKEN", ""), REPOSITORY)
        results = []
        for number in sorted(set(args.issue)):
            try:
                results.append(verify_ready_issue(api, number))
            except Exception as exc:
                # Bounded reason only, never private Issue body, credentials,
                # model text or raw response excerpts.
                reason = str(exc)
                if not re.fullmatch(r"[A-Z][A-Z0-9_]{3,79}", reason):
                    reason = type(exc).__name__.upper()
                results.append({"issue": number, "status": "BLOCKED",
                                "reason": reason,
                                "execution_authorized_by_preflight": False})
        for number in sorted(set(args.expect_held)):
            try:
                results.append(verify_held_issue(api, number))
            except Exception as exc:
                reason = str(exc)
                if not re.fullmatch(r"[A-Z][A-Z0-9_]{3,79}", reason):
                    reason = type(exc).__name__.upper()
                results.append({"issue": number, "status": "BLOCKED",
                                "reason": reason,
                                "execution_authorized_by_preflight": False})
        print("LOCAL9B_APPROVED_ISSUE_PREFLIGHT=" +
              json.dumps(results, sort_keys=True, ensure_ascii=False))
        return 2 if any(row["status"] == "BLOCKED" for row in results) else 0
    except Exception as exc:
        print("LOCAL9B_APPROVED_ISSUE_PREFLIGHT=BLOCKED:" +
              type(exc).__name__.upper(), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
