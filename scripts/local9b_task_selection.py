"""Versioned, deterministic and model-free priority policy for approved local9B tasks.

Discovery is deliberately separate from execution authority. Raw CI output, issue
prose and model rankings cannot create or upgrade a runnable task.
"""
from __future__ import annotations
import re

POLICY_VERSION = "local9b-task-selection/v1"
PRIORITY = {f"foundation-autodev:p{p}": p for p in range(4)}
HOLD = "foundation-autodev:hold"

# A pinned independent regression is stronger evidence than the legacy static
# smoke recipe. Neither is a licence to change tests, authorizations or scope.
EVIDENCE = {"python-fixed-test": (0, "PINNED_TEST_BASELINE_REPRO_REQUIRED"),
            "bounded-http-positive-limit": (1, "HOST_FIXED_SMOKE_BASELINE_REPRO_REQUIRED")}


def _labels(issue):
    labels = issue.get("labels", [])
    if type(labels) is not list or any(type(item) is not dict or
                                       type(item.get("name")) is not str for item in labels):
        raise ValueError("ISSUE_LABELS_INVALID")
    return {item["name"] for item in labels}


def admission(issue):
    """Labels rank *already approved* issues; they never grant approval."""
    labels = _labels(issue)
    if HOLD in labels:
        return {"status": "HELD", "reason": "EXPLICIT_HOLD_LABEL"}
    requested = sorted((name for name in labels if name in PRIORITY))
    if len(requested) > 1:
        return {"status": "NEEDS_PRIORITY_REVIEW",
                "reason": "CONFLICTING_PRIORITY_LABELS"}
    rank = PRIORITY[requested[0]] if requested else 2
    return {"status": "ELIGIBLE", "priority": f"P{rank}",
            "priority_rank": rank, "policy_version": POLICY_VERSION}


def evidence(task):
    """Only supported bounded host recipes are selectable."""
    recipe = task.get("recipe", "bounded-http-positive-limit")
    if recipe not in EVIDENCE:
        raise ValueError("UNSUPPORTED_SELECTION_RECIPE")
    rank, reason = EVIDENCE[recipe]
    return {"evidence_rank": rank, "evidence_gate": reason}


def ordered_reports(reports):
    """FIFO within explicit severity and evidence class; no LLM sorting."""
    return sorted(reports, key=lambda item: (
        item.get("status") != "QUEUED",
        item.get("priority_rank", 4),
        item.get("evidence_rank", 9),
        item.get("issue") if type(item.get("issue")) is int else 2**63,
        item.get("task", ""),
    ))


def queued_tasks(reports):
    """The only execution queue: currently approved and unconsumed intake."""
    for item in ordered_reports(reports):
        if item.get("status") == "QUEUED":
            task_id = item.get("task")
            if type(task_id) is not str or not re.fullmatch(r"issue-[1-9][0-9]*-[a-f0-9]{16}", task_id):
                raise ValueError("UNTRUSTED_EXECUTION_QUEUE")
            yield task_id
