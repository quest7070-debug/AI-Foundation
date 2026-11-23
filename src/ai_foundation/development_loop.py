"""Bounded CODE loop using existing host-bound AgentPort and Guard tools.

The host supplies a proposal-only agent, independent fixed acceptance port,
and (optionally) its existing Draft PR publisher. This owns no Native session.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import re

from .agent import AgentRequest


@dataclass(frozen=True)
class DevelopmentLoopResult:
    status: str
    attempts: int
    source_sha256: str = ""
    feedback: str = ""
    delivery_ref: str = ""


@dataclass(frozen=True)
class TestAcceptanceReceipt:
    """Host-run result; passed must come from a trusted test process exit code."""
    passed: bool
    detail: str


def _legacy_acceptance_passed(output: str) -> bool:
    """Transitional support for existing trusted, text-only host runners.

    Arbitrary nonempty text is not proof. Unknown/ambiguous receipts fail closed.
    """
    if re.search(r"\b(?:fail|failed|failure|error|errors|traceback|tests_failed)\b",
                 output, re.IGNORECASE):
        return False
    summary = output.strip().splitlines()[-1].strip().strip("= ").strip()
    if summary == "PASS":
        return True
    # Existing fixed Mac test runner: "7 ... cases and valid lifecycle PASS".
    if re.fullmatch(r"\d+ [A-Za-z0-9_ /.-]{1,180} PASS", summary):
        return True
    # Explicit pytest summary, not a free-form message claiming success.
    return re.fullmatch(
        r"\d+ passed(?:, \d+ (?:skipped|xfailed|xpassed|deselected|warnings?))*"
        r"(?: in \d+(?:\.\d+)?s)?",
        summary,
    ) is not None



def _typed_receipt_reports_failure(detail: str) -> bool:
    """Reject contradictory test *results*, not harmless warning/log vocabulary.

    A typed receipt's true success authority is its host-observed exit code.
    Structured pytest/fixed-runner failure summaries contradict that success,
    while free-form warnings such as "fallback for error reporting" do not.
    """
    summaries = (
        r"(?:\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|"
        r"deselected|warnings?))"
        r"(?:, \d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|"
        r"deselected|warnings?))*"
        r"(?: in \d+(?:\.\d+)?s)?"
    )
    for line in detail.splitlines():
        summary = line.strip().strip("= ").strip()
        if summary.upper() in {"FAIL", "FAILED", "ERROR", "TESTS_FAILED"}:
            return True
        if (re.fullmatch(summaries, summary, re.IGNORECASE)
                and re.search(r"\b[1-9]\d* (?:failed|errors?)\b",
                              summary, re.IGNORECASE)):
            return True
    return False


def run_development_loop(*, specialist, agent, instruction: str, target: str,
                         acceptance_target: str, max_repairs: int = 1,
                         publish_draft=None, repair_agent=None,
                         review_agent=None) -> DevelopmentLoopResult:
    """One initial edit plus at most two repairs; every write still uses Guard.

    Agent output is the complete replacement file, never a command or target.
    The acceptance target is host-selected. Failed tests feed the next proposal;
    denied/uncertain writes and infrastructure failures are never retried.
    Exceptions propagate so callers cannot turn transport errors into success.
    """
    if type(max_repairs) is not int or not 0 <= max_repairs <= 2:
        raise ValueError("INVALID_REPAIR_BUDGET")
    if not all(type(x) is str and x.strip() for x in
               (instruction, target, acceptance_target)):
        raise ValueError("INCOMPLETE_DEVELOPMENT_TASK")
    tools = specialist.tools
    safe_target = tools.write_capability.authorize_target(target)
    # This small loop cannot modify its own acceptance tests.
    if tools.read_capability.authorize_target(acceptance_target) == safe_target:
        raise ValueError("ACCEPTANCE_MUST_BE_INDEPENDENT")
    if specialist.protected is not None:
        specialist.protected.validate_write(safe_target)
    current = tools.read(target)
    seen = {sha256(current.encode()).hexdigest()}
    feedback = "Initial implementation; acceptance has not run."
    for attempt in range(1, max_repairs + 2):
        prompt = json.dumps({
            "instruction": instruction,
            "current_source": current,
            "test_feedback": feedback[-8000:],
            "response_format": "Return only the complete replacement file, without Markdown fences.",
        }, ensure_ascii=False)
        try:
            candidate = (agent if attempt == 1 or repair_agent is None
                         else repair_agent).run(AgentRequest(prompt)).output
        except SyntaxError as error:
            feedback = "PROPOSAL_SYNTAX_ERROR: " + str(error)
            continue
        except PermissionError:
            return DevelopmentLoopResult("PROPOSAL_POLICY_DENIED", attempt)
        except (TimeoutError, OSError, RuntimeError) as error:
            # Provider/CLI failure is not faulty generated code. No extra
            # model turn, write, test or Draft; never export its raw message.
            return DevelopmentLoopResult(
                "PROPOSAL_RUNTIME_UNAVAILABLE", attempt, feedback=type(error).__name__)
        except ValueError:
            # A malformed Harness response does not justify writing a guess.
            return DevelopmentLoopResult("PROPOSAL_INVALID", attempt)
        if type(candidate) is not str or not candidate.strip() or len(candidate.encode()) > 262144:
            return DevelopmentLoopResult("INVALID_PROPOSAL", attempt)
        digest = sha256(candidate.encode()).hexdigest()
        if digest in seen:
            return DevelopmentLoopResult("NO_PROGRESS", attempt, digest, feedback)
        seen.add(digest)
        write = tools.write(target, candidate)
        if write != "VERIFIED_COMPLETE":
            return DevelopmentLoopResult("WRITE_NOT_VERIFIED", attempt, feedback=str(write))
        current = tools.read(target)
        if current != candidate:
            return DevelopmentLoopResult("WRITE_READBACK_MISMATCH", attempt)
        try:
            # Prefer a typed receipt from the host's subprocess exit status.
            # Keep explicitly parsed legacy receipts for current fixed runners.
            runner = getattr(specialist.tests, "run_acceptance", None)
            receipt = (runner(acceptance_target) if callable(runner)
                       else specialist.tests.run_tests(acceptance_target))
        except RuntimeError as error:
            if callable(runner):
                # A typed host runner reports test failures through its receipt.
                # An exception here is an infrastructure failure, not a failed
                # source test. Never spend another model turn or publish Draft.
                return DevelopmentLoopResult(
                    "TEST_RUNNER_UNAVAILABLE", attempt, digest, type(error).__name__)
            # Legacy text-only host runners still raise on ordinary test failure.
            feedback = str(error)[-8000:]
            continue
        if isinstance(receipt, TestAcceptanceReceipt):
            if type(receipt.passed) is not bool or type(receipt.detail) is not str:
                return DevelopmentLoopResult("TEST_ACCEPTANCE_UNVERIFIED", attempt, digest)
            feedback = receipt.detail[-8000:]
            if not receipt.passed:
                # A real test failure still consumes the existing bounded repair
                # budget; it never reaches the publisher.
                feedback = feedback or "TEST_ACCEPTANCE_FAILED"
                continue
            if not feedback.strip() or _typed_receipt_reports_failure(feedback):
                return DevelopmentLoopResult("TEST_ACCEPTANCE_UNVERIFIED", attempt, digest, feedback)
        elif type(receipt) is str:
            feedback = receipt[-8000:]
            if not feedback.strip():
                return DevelopmentLoopResult("TEST_ACCEPTANCE_UNVERIFIED", attempt, digest)
            if re.search(r"\b(?:fail|failed|failure|error|errors|traceback|tests_failed)\b",
                         feedback, re.IGNORECASE):
                return DevelopmentLoopResult("TEST_ACCEPTANCE_FAILED", attempt, digest, feedback)
            if not _legacy_acceptance_passed(feedback):
                return DevelopmentLoopResult("TEST_ACCEPTANCE_UNVERIFIED", attempt, digest, feedback)
        else:
            return DevelopmentLoopResult("TEST_ACCEPTANCE_UNVERIFIED", attempt, digest)
        # Re-read after independent tests, before handing source to delivery.
        if tools.read(target) != candidate:
            return DevelopmentLoopResult("SOURCE_CHANGED_DURING_TEST", attempt)
        if review_agent is not None:
            approved = review_agent.review(
                target=target, source=candidate, source_sha256=digest,
                acceptance_target=acceptance_target, feedback=feedback)
            if approved is not True:
                return DevelopmentLoopResult("REVIEW_BLOCKED", attempt, digest, feedback)
            if tools.read(target) != candidate:
                return DevelopmentLoopResult("SOURCE_CHANGED_DURING_REVIEW", attempt)
        if publish_draft is None:
            return DevelopmentLoopResult("TESTED_CHANGE", attempt, digest, feedback)
        delivery = publish_draft(target=target, source_sha256=digest)
        if type(delivery) is not str or not delivery.strip():
            return DevelopmentLoopResult("DELIVERY_UNVERIFIED", attempt, digest, feedback)
        return DevelopmentLoopResult("DRAFT_PR_PRESENTED", attempt, digest, feedback, delivery)
    return DevelopmentLoopResult("REPAIR_BUDGET_EXHAUSTED", max_repairs + 1,
                                 sha256(current.encode()).hexdigest(), feedback)
