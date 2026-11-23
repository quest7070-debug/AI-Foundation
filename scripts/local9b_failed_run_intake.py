"""Convert consumed local9B fixed-test failures into review-only candidate events.

The owned 9B worker consumes an approved GitHub Issue *once*. A failed run may
generate a separate diagnostic follow-up proposal, never replay that authority
or add the 'ready' label. Neither model output nor untrusted pytest text may
select files, commands, base branch or success criteria here.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile

from local9b_task_recipe import validate_contract

TASK_NAME = re.compile(r"issue-([1-9][0-9]*)-([a-f0-9]{16})")
CANDIDATE_SCHEMA = "local9b-failed-attempt-candidate/v1"
# Only bounded test-edit outcomes. A failed/uncertain write or delivery needs
# independent *effect reconciliation*, not another model-generated attempt.
REPAIRABLE = frozenset({
    "REPAIR_BUDGET_EXHAUSTED",
    "NO_PROGRESS",
    "INVALID_PROPOSAL",
})
MAX_RESULT_RECEIPTS = 1024
MAX_CAPTURE_PER_TICK = 8
MAX_RECEIPT_BYTES = 16384
# Stable, non-sensitive diagnostic categories. Never store raw stderr,
# model-generated source or a guessed root cause in a GitHub Issue.
FAILURE_CLASSES = frozenset({
    "GENERATED_SOURCE_SYNTAX_ERROR",
    "PROPOSAL_SYNTAX_ERROR",
    "PINNED_TEST_FAILED",
    "NO_PROGRESS",
    "INVALID_PROPOSAL",
    "UNCLASSIFIED_FAILURE",
})


def classify_failure(status: str, feedback: str) -> str:
    """Classify only host-produced evidence. No LLM, prose parsing or trust grant."""
    if status == "NO_PROGRESS":
        return "NO_PROGRESS"
    if status == "INVALID_PROPOSAL":
        return "INVALID_PROPOSAL"
    if feedback.startswith("GENERATED_SOURCE_SYNTAX_ERROR:"):
        return "GENERATED_SOURCE_SYNTAX_ERROR"
    if feedback.startswith("PROPOSAL_SYNTAX_ERROR:"):
        return "PROPOSAL_SYNTAX_ERROR"
    # FixedPytest emits a pytest failure count; do not use test text as commands.
    if re.search(r"(?:^|\n)FAILED\s|\b[1-9][0-9]* failed\b", feedback):
        return "PINNED_TEST_FAILED"
    return "UNCLASSIFIED_FAILURE"


def _json_file(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RECEIPT_BYTES:
        raise ValueError("UNTRUSTED_AUTODEV_RECEIPT")
    def reject_duplicate_pairs(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("DUPLICATE_RECEIPT_KEY")
            obj[key] = value
        return obj
    raw = json.loads(path.read_text(encoding="utf-8"),
                     object_pairs_hook=reject_duplicate_pairs)
    if type(raw) is not dict:
        raise ValueError("AUTODEV_RECEIPT_NOT_OBJECT")
    return raw


def candidate_from_attempt(root: Path, receipt_file: Path) -> dict | None:
    """Verify existing host markers, exact fixed recipe and local result.

    Never parse model stderr to infer commands, affected modules, success,
    actor identity or privileges. No mutation and no network here.
    """
    root = Path(root)
    if ((root / "inbox").is_symlink() or (root / "results").is_symlink()
            or (root / "failures").is_symlink()):
        raise ValueError("UNTRUSTED_AUTODEV_DIRECTORY")
    if receipt_file.parent != root / "results":
        raise ValueError("RESULT_OUTSIDE_OWNED_DIRECTORY")
    match = TASK_NAME.fullmatch(receipt_file.stem)
    if match is None:
        return None
    result = _json_file(receipt_file)
    status = result.get("status")
    if status not in REPAIRABLE:
        return None
    issue_num = int(match.group(1))
    task_id = receipt_file.stem
    claimed = root / "results" / f"issue-{issue_num}.claimed"
    started = root / "results" / f"{task_id}.started"
    inbox = root / "inbox" / f"{task_id}.json"
    if (claimed.is_symlink() or started.is_symlink() or inbox.is_symlink()
            or not claimed.is_file() or not started.is_file()):
        raise ValueError("ORIGINAL_ATTEMPT_EVIDENCE_MISSING")
    if claimed.read_text(encoding="utf-8").strip() != inbox.name:
        raise ValueError("ORIGINAL_ISSUE_CLAIM_MISMATCH")
    task = _json_file(inbox)
    if (task.get("id") != task_id or task.get("source_issue") != issue_num
            or type(task.get("source_digest")) is not str
            or re.fullmatch(r"[a-f0-9]{64}", task["source_digest"]) is None):
        raise ValueError("ORIGINAL_ISSUE_IDENTITY_MISMATCH")
    contract_fields = ("recipe", "base", "base_sha", "target",
                       "test", "test_sha256", "instruction")
    if not all(k in task for k in contract_fields):
        return None  # legacy recipe: not a fixed-test failure.
    contract = {k: task[k] for k in contract_fields}
    validate_contract(contract)
    if (result.get("unattended") is not True
            or result.get("model") != "qwen3.5:9b"
            or result.get("production_activated") is not False
            or type(result.get("attempts")) is not int
            or not 1 <= result["attempts"] <= 3
            or result.get("delivery_ref") not in ("", None)):
        raise ValueError("UNTRUSTED_TERMINAL_FAILURE_RESULT")
    feedback = result.get("feedback") or ""
    if type(feedback) is not str or len(feedback) > 8192:
        raise ValueError("UNBOUNDED_FAILURE_FEEDBACK")
    # Extra origin fields are host-supplied diagnostic metadata; the existing
    # publisher will reconstruct and re-run its canonical contract on a clean
    # pinned checkout before creating an Issue. No ready label is set.
    return {
        "base": contract["base"], "target": contract["target"],
        "test": contract["test"], "instruction": contract["instruction"],
        "origin": {
            "schema": CANDIDATE_SCHEMA,
            "issue": issue_num,
            "attempt": task_id,
            "result_status": status,
            "attempts": result["attempts"],
            "feedback_sha256": sha256(feedback.encode("utf-8")).hexdigest(),
            "failure_class": classify_failure(status, feedback),
            "original_base_sha": contract["base_sha"],
            "original_test_sha256": contract["test_sha256"],
            "approval_reusable": False,
        },
    }


def capture_failed_run_candidates(root: Path) -> list[dict]:
    """Materialize at most eight deduplicated proposals for existing publisher.

    Capture is atomic, source-only, independent of model/resource availability.
    Captured JSON is not an approved Issue and cannot authorize another run.
    """
    root = Path(root)
    results = root / "results"
    failures = root / "failures"
    if results.is_symlink() or not results.is_dir():
        raise ValueError("UNTRUSTED_AUTODEV_RESULTS")
    # Directory authority is global, not a malformed individual receipt.
    # Never turn a redirected inbox into a silently skipped attempt.
    if (root / "inbox").is_symlink():
        raise ValueError("UNTRUSTED_AUTODEV_DIRECTORY")
    if failures.is_symlink():
        raise ValueError("UNTRUSTED_AUTODEV_FAILURES")
    failures.mkdir(mode=0o700, exist_ok=True)
    files = sorted(results.glob("issue-*-*.json"))
    if len(files) > MAX_RESULT_RECEIPTS:
        raise ValueError("AUTODEV_FAILURE_INVENTORY_INCOMPLETE")
    collected = []
    captured = 0
    skipped = 0
    for source in files:
        if captured >= MAX_CAPTURE_PER_TICK:
            break
        try:
            proposal = candidate_from_attempt(root, source)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            # A malformed/stale completed attempt is not permission to infer
            # a different contract or replay it. Reject *this record* only:
            # otherwise the first bad receipt starves every unrelated owned
            # failure on every scheduled tick. Publish no raw path, data or
            # exception string; the original receipt stays for owner review.
            if skipped < MAX_CAPTURE_PER_TICK:
                collected.append({
                    "status": "UNTRUSTED_ATTEMPT_SKIPPED",
                    "issue": int(TASK_NAME.fullmatch(source.stem).group(1)),
                })
            skipped += 1
            continue
        if proposal is None:
            continue
        dest = failures / ("autodev-" + source.name)
        if dest.is_symlink():
            raise ValueError("UNTRUSTED_AUTODEV_CANDIDATE")
        payload = json.dumps(proposal, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"))
        if dest.exists():
            if dest.read_text(encoding="utf-8") != payload:
                raise ValueError("FAILURE_CANDIDATE_CHANGED_AFTER_CAPTURE")
            continue
        # Candidate metadata belongs to the owner and must never exist
        # world-readable, even briefly under a permissive process umask.
        # Link the completely written private inode only after fsync:
        # unlike replace(), link() cannot overwrite a concurrent candidate.
        fd, tmp = tempfile.mkstemp(
            prefix="." + dest.name + ".", suffix=".tmp", dir=failures)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(tmp, dest)
        finally:
            Path(tmp).unlink(missing_ok=True)
        collected.append({"status": "CAPTURED_FOR_DIAGNOSTIC_REVIEW",
                          "issue": proposal["origin"]["issue"],
                          "result_status": proposal["origin"]["result_status"]})
        captured += 1
    return collected
