from ai_foundation.job_notification_policy import (
    ImportantJobEvent,
    project_important_job_event,
)
import pytest


@pytest.mark.parametrize("kind", [e.value for e in ImportantJobEvent])
def test_only_four_important_events_are_projected(kind):
    notice = project_important_job_event(job_id="job-1", kind=kind, revision=2, source_id="native-1")
    assert notice is not None
    assert notice.kind.value == kind


@pytest.mark.parametrize("kind", ["RUNNING", "TEST_PASSED", "RETRY", "AUTO_RECOVERED", "PROGRESS", ""])
def test_routine_event_never_proactively_notifies(kind):
    assert project_important_job_event(job_id="job-1", kind=kind, revision=2, source_id="native-1") is None


def test_stable_dedupe_identity_and_revision_separation():
    kwargs = dict(job_id="job-1", kind="APPROVAL_REQUIRED", revision=1, source_id="gate-42")
    first = project_important_job_event(**kwargs)
    assert first.event_id == project_important_job_event(**kwargs).event_id
    assert first.event_id != project_important_job_event(**(kwargs | {"revision": 2})).event_id
    assert first.event_id != project_important_job_event(**(kwargs | {"source_id": "gate-43"})).event_id


def test_no_untrusted_payload_is_in_title_or_identity():
    notice = project_important_job_event(job_id="job-1", kind="ANSWER_REQUIRED", revision=1, source_id="q-1")
    assert "job-1" not in notice.title
    assert "q-1" not in notice.title


@pytest.mark.parametrize("kwargs", [
    {"job_id": "", "kind": "JOB_COMPLETED", "revision": 0, "source_id": "x"},
    {"job_id": "x", "kind": "JOB_COMPLETED", "revision": -1, "source_id": "x"},
    {"job_id": "x", "kind": "JOB_COMPLETED", "revision": True, "source_id": "x"},
    {"job_id": "x", "kind": "JOB_COMPLETED", "revision": 0, "source_id": ""},
])
def test_invalid_identity_is_rejected(kwargs):
    with pytest.raises(ValueError):
        project_important_job_event(**kwargs)
