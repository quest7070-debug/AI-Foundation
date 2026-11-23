"""Corroborate an attributed Muse history statement against independent Drive/M1 facts.

OPERATIONALLY_CORROBORATED describes cross-source consistency, NOT
authenticated Muse execution, review, or execution authorization.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping

from .muse_delivery_state import EvidenceError, REQUEST
from .muse_run_chronology import ClaimedRunWindow, DriveFileEvent, assess_run_report_chronology

_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{3,128}$")
_TASK_ID = re.compile(r"^[A-Za-z0-9_-]{3,128}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class MuseHistoryStatement:
    request_id: str
    correlation_id: str
    run_id: str
    scheduler_id: str
    started_at: str
    finished_at: str
    status: str
    request_read_observed: bool
    report_created_observed: bool
    source_kind: str = "muse-run-history-reported"


def corroborate_operational_run(
    statement: MuseHistoryStatement, *,
    original: DriveFileEvent,
    transfer: DriveFileEvent,
    expected_folder_id: str,
    source_only_inventory: Mapping[str, object],
) -> dict:
    if not isinstance(statement, MuseHistoryStatement):
        raise EvidenceError("invalid Muse run history statement")
    if not REQUEST.fullmatch(statement.request_id):
        raise EvidenceError("invalid request ID")
    if not _RUN_ID.fullmatch(statement.run_id) or not _TASK_ID.fullmatch(statement.scheduler_id):
        raise EvidenceError("invalid scheduler identity")
    if statement.source_kind != "muse-run-history-reported":
        raise EvidenceError("unsupported stated run provenance")
    if statement.status != "succeeded" or statement.request_read_observed is not True or statement.report_created_observed is not True:
        raise EvidenceError("incomplete reported scheduler execution")
    if not statement.correlation_id or not statement.correlation_id.endswith(statement.request_id.removeprefix("REQ-")):
        raise EvidenceError("reported correlation does not bind request")
    if not isinstance(source_only_inventory, Mapping):
        raise EvidenceError("source-only inventory missing")
    if (source_only_inventory.get("request_id") != statement.request_id
            or source_only_inventory.get("correlation_id") != statement.correlation_id
            or source_only_inventory.get("source_only_integrity_verified") is not True
            or source_only_inventory.get("execution_authorized") is not False
            or source_only_inventory.get("disposition") != "HOLD_UNVERIFIED"):
        raise EvidenceError("source-only report evidence is not validated")
    digest = source_only_inventory.get("candidate_sha256")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise EvidenceError("missing canonical candidate hash")
    chronology = assess_run_report_chronology(
        ClaimedRunWindow(
            request_id=statement.request_id, run_id=statement.run_id,
            started_at=statement.started_at, finished_at=statement.finished_at,
            evidence_origin=statement.source_kind,
        ),
        original, transfer, expected_folder_id=expected_folder_id,
    )
    if not chronology["chronology_consistent"]:
        raise EvidenceError("Drive chronology does not corroborate the stated run")
    return {
        "request_id": statement.request_id,
        "correlation_id": statement.correlation_id,
        "reported_run_id": statement.run_id,
        "scheduler_id": statement.scheduler_id,
        "run_statement_source": statement.source_kind,
        "original_drive_file_id": original.file_id,
        "transfer_drive_file_id": transfer.file_id,
        "source_only_candidate_sha256": digest,
        "findings_count": source_only_inventory.get("findings_count"),
        "chronology_consistent": True,
        "source_only_integrity_verified": True,
        "classification": "OPERATIONALLY_CORROBORATED",
        "muse_execution_authenticated": False,
        "run_output_authorship_verified": False,
        "independent_review_authenticated": False,
        "native_e2e_accepted": False,
        "execution_authorized": False,
        "lifecycle_stage_advanced": False,
        "disposition": "HOLD_UNVERIFIED",
    }
