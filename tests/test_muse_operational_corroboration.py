from dataclasses import replace

import pytest
from ai_foundation.muse_delivery_state import EvidenceError
from ai_foundation.muse_operational_corroboration import (
    MuseHistoryStatement, corroborate_operational_run)
from ai_foundation.muse_run_chronology import DriveFileEvent

RID = "REQ-20261102-008"
CID = "scout:muse-native-daily-inbox-20261102-008"
FOLDER = "findings-folder"


def items():
    run = MuseHistoryStatement(
        RID, CID, "38cb5220-b391-4729-9dd1-97b84da27232",
        "drive-10-requests-monitor", "2026-11-03T09:38:00+09:00",
        "2026-11-03T09:56:11+09:00", "succeeded", True, True)
    original = DriveFileEvent("original", "MUSE-REPORT-"+RID,
                              "2026-11-03T00:52:42.869Z", FOLDER)
    transfer = DriveFileEvent("export", "MUSE-REPORT-"+RID+".txt",
                              "2026-11-03T02:47:43.674Z", FOLDER)
    intake = dict(request_id=RID, correlation_id=CID,
                  source_only_integrity_verified=True,
                  candidate_sha256="f"*64, findings_count=8,
                  execution_authorized=False, disposition="HOLD_UNVERIFIED")
    return run, original, transfer, intake


def check(run, original, transfer, intake):
    return corroborate_operational_run(
        run, original=original, transfer=transfer,
        expected_folder_id=FOLDER, source_only_inventory=intake)


def test_complete_statement_and_independent_evidence_is_operational_only():
    result = check(*items())
    assert result["classification"] == "OPERATIONALLY_CORROBORATED"
    assert not result["muse_execution_authenticated"]
    assert not result["native_e2e_accepted"]
    assert not result["execution_authorized"]
    assert not result["lifecycle_stage_advanced"]
    assert result["disposition"] == "HOLD_UNVERIFIED"


@pytest.mark.parametrize("changes", [
    {"request_id": "REQ-20261101-003"}, {"correlation_id": "unrelated"},
    {"status": "failed"}, {"request_read_observed": False},
    {"report_created_observed": False}, {"source_kind": "user-asserted"},
    {"scheduler_id": ""}, {"run_id": ""},
])
def test_mismatched_or_incomplete_statement_fails_closed(changes):
    run,original,transfer,intake=items()
    with pytest.raises(EvidenceError):
        check(replace(run, **changes),original,transfer,intake)


@pytest.mark.parametrize("changes", [
    {"candidate_sha256": None}, {"execution_authorized": True},
    {"request_id": "REQ-20261101-003"}, {"source_only_integrity_verified":False},
    {"disposition": "MUSE_ACCEPTED"}, {"correlation_id":"another"},
])
def test_untrusted_source_only_inventory_fails_closed(changes):
    run,original,transfer,intake=items()
    with pytest.raises(EvidenceError):
        check(run,original,transfer,intake|changes)


def test_chronology_inconsistent_fails_closed():
    run,original,transfer,intake=items()
    original=replace(original,created_at="2026-11-03T08:00:00+09:00")
    with pytest.raises(EvidenceError):
        check(run,original,transfer,intake)


def test_wrong_drive_parent_fails_closed():
    run,original,transfer,intake=items()
    with pytest.raises(EvidenceError):
        check(run,replace(original,folder_id="other"),transfer,intake)
