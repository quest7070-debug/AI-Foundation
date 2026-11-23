"""Read-only chronology for a claimed Muse run and two Drive file events.

A plausible creation time is NOT an authenticated Muse run or an output
attestation. Neither can this function advance any delivery lifecycle stage.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .muse_delivery_state import EvidenceError, REQUEST


@dataclass(frozen=True)
class ClaimedRunWindow:
    request_id: str
    run_id: str
    started_at: str
    finished_at: str
    evidence_origin: str = "user-reported"


@dataclass(frozen=True)
class DriveFileEvent:
    file_id: str
    title: str
    created_at: str
    folder_id: str


def _time(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise EvidenceError("invalid chronology timestamp") from exc
    if parsed.tzinfo is None:
        raise EvidenceError("timezone is required")
    return parsed.astimezone(dt.timezone.utc)


def assess_run_report_chronology(
    claimed: ClaimedRunWindow, original: DriveFileEvent,
    transfer: DriveFileEvent, *, expected_folder_id: str,
) -> dict:
    if not REQUEST.fullmatch(claimed.request_id) or not claimed.run_id:
        raise EvidenceError("invalid run identity")
    if not expected_folder_id or original.folder_id != expected_folder_id or transfer.folder_id != expected_folder_id:
        raise EvidenceError("Drive folder identity mismatch")
    expected = "MUSE-REPORT-" + claimed.request_id
    if original.title != expected or transfer.title != expected + ".txt":
        raise EvidenceError("report identity mismatch")
    if original.file_id == transfer.file_id or not original.file_id or not transfer.file_id:
        raise EvidenceError("distinct original and transfer files required")
    start, end = _time(claimed.started_at), _time(claimed.finished_at)
    original_created, transferred = _time(original.created_at), _time(transfer.created_at)
    if end < start or end - start > dt.timedelta(hours=24):
        raise EvidenceError("invalid claimed run window")
    original_inside = start <= original_created <= end
    transfer_after = transferred >= original_created
    return {
        "request_id": claimed.request_id,
        "run_id_reported": claimed.run_id,
        "run_time_source": claimed.evidence_origin,
        "original_created_during_claimed_run": original_inside,
        "transfer_created_after_original": transfer_after,
        "chronology_consistent": original_inside and transfer_after,
        "muse_execution_authenticated": False,
        "run_output_authorship_verified": False,
        "independent_review_authenticated": False,
        "native_e2e_accepted": False,
        "disposition": "HOLD_UNVERIFIED",
    }
