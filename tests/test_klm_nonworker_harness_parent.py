"""Exact non-executable Harness parent must not starve the existing KLM 9B."""
import tempfile
from pathlib import Path

from ai_foundation.klm_drive_work import (
    _exact_non_worker_harness_parent, read_development_state,
)

PARENT_BODY = """## Real Harness two-source parent
<!-- foundation-autodev: {"paths":["src/ai_foundation/agent.py","src/ai_foundation/development_loop.py"],"depends_on":[]} -->
**EXACT_PARENT_SCOPE_APPROVED / NO CHILD EXECUTION YET.**
The parent has no executable foundation-autodev-task block. Do not treat it as worker Work.
"""


def issue(number=555, body=PARENT_BODY):
    return {"number": number, "body": body, "state": "OPEN",
            "labels": [{"name": "foundation-autodev:ready"}]}


def observe(item, *, executable=False):
    class Bridge:
        REPOSITORY = "quest7070-dev/AI-Foundation"
        READY_LABEL = "foundation-autodev:ready"

        @staticmethod
        def _gh(*args):
            return [item]

        @staticmethod
        def issue_task(row):
            if not executable:
                raise ValueError("NO_FINITE_TASK")
            return {"source_issue": row["number"]}

        @staticmethod
        def previous_issue_attempt(*args):
            return False

    class Selection:
        @staticmethod
        def admission(row):
            return {"status": "ELIGIBLE"}

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "inbox").mkdir()
        (root / "results").mkdir()
        return read_development_state(root, Bridge, Selection, now=lambda: 1000)


def test_exact_parent_does_not_create_fake_9b_backlog():
    row = issue()
    assert _exact_non_worker_harness_parent(row) is True
    state = observe(row)
    assert state.complete is True
    assert state.approved_pending == 0
    assert state.non_worker_approved == 1
    assert state.native_only_approved == 0
    assert state.active_or_uncertain == 0
    assert state.idle(1000) is True


def test_unrelated_ready_issue_remains_conservatively_pending():
    assert _exact_non_worker_harness_parent(issue(556)) is False
    state = observe(issue(556))
    assert state.approved_pending == 1
    assert state.non_worker_approved == 0
    assert state.idle(1000) is False


def test_explicit_executable_child_marker_prevents_parent_bypass():
    body = PARENT_BODY + '\n<!-- foundation-autodev-task: {"task":"9b"} -->'
    assert _exact_non_worker_harness_parent(issue(body=body)) is False
    assert observe(issue(body=body)).approved_pending == 1


def test_missing_owner_parent_authority_does_not_bypass():
    body = PARENT_BODY.replace("**EXACT_PARENT_SCOPE_APPROVED / NO CHILD EXECUTION YET.**", "")
    assert _exact_non_worker_harness_parent(issue(body=body)) is False
    assert observe(issue(body=body)).approved_pending == 1


def test_different_scope_and_duplicate_contract_keys_do_not_bypass():
    mutated = PARENT_BODY.replace("development_loop.py", "unrelated.py")
    dup = PARENT_BODY.replace('"depends_on":[]', '"depends_on":[],"depends_on":[]')
    for body in (mutated, dup):
        assert _exact_non_worker_harness_parent(issue(body=body)) is False
        assert observe(issue(body=body)).approved_pending == 1


def test_real_finite_worker_issue_still_blocks_even_with_parent_description():
    # The helper classifies this *specific* parent scope before calling
    # issue_task. A different finite worker task is still never exempted.
    state = observe(issue(556), executable=True)
    assert state.approved_pending == 1
    assert state.non_worker_approved == 0
    assert state.idle(1000) is False
