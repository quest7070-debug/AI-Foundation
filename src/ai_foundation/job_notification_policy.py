"""Deterministic policy for proposed Foundation Job notifications.

This module deliberately does not send messages, manage approvals or change the
existing Operator/notification runtime. Transport and durable outbox are later,
separately gated integration steps.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib


class ImportantJobEvent(str, Enum):
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    ANSWER_REQUIRED = "ANSWER_REQUIRED"
    CRITICAL_INCIDENT = "CRITICAL_INCIDENT"
    JOB_COMPLETED = "JOB_COMPLETED"


@dataclass(frozen=True)
class ImportantJobNotice:
    event_id: str
    job_id: str
    kind: ImportantJobEvent
    revision: int
    # Safe generic preview: no task text, secret, or provider payload.
    title: str


_TITLES = {
    ImportantJobEvent.APPROVAL_REQUIRED: "承認が必要です",
    ImportantJobEvent.ANSWER_REQUIRED: "回答が必要です",
    ImportantJobEvent.CRITICAL_INCIDENT: "重大な問題が発生しました",
    ImportantJobEvent.JOB_COMPLETED: "Jobが完了しました",
}


def project_important_job_event(
    *, job_id: str, kind: str, revision: int, source_id: str
) -> ImportantJobNotice | None:
    """Project only the four operator-approved proactive notification kinds.

    A projection is *not* proof that a decision is valid or a Job is finished.
    The caller must independently verify native Guard/Job source state and
    enforce delivery authorization. Invalid identities fail closed.
    """
    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("job_id required")
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id required")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise ValueError("nonnegative integer revision required")
    try:
        event_kind = ImportantJobEvent(kind)
    except (ValueError, TypeError):
        # Routine progress/retries must not be promoted to a proactive notice.
        return None
    identity = "\x1f".join((job_id, event_kind.value, str(revision), source_id))
    event_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return ImportantJobNotice(
        event_id=event_id,
        job_id=job_id,
        kind=event_kind,
        revision=revision,
        title=_TITLES[event_kind],
    )
