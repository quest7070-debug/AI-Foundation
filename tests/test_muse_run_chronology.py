from dataclasses import replace
import pytest

from ai_foundation.muse_delivery_state import EvidenceError
from ai_foundation.muse_run_chronology import (
    ClaimedRunWindow, DriveFileEvent, assess_run_report_chronology,
)

RID = "REQ-20261102-008"
FOLDER = "20-findings-folder"


def fixture():
    run = ClaimedRunWindow(RID, "38cb5220-b391-4729-9dd1-97b84da27232",
                           "2026-11-03T09:38:00+09:00",
                           "2026-11-03T09:56:11+09:00")
    original = DriveFileEvent("original-id", "MUSE-REPORT-" + RID,
                              "2026-11-03T00:52:42.869Z", FOLDER)
    transfer = DriveFileEvent("transfer-id", "MUSE-REPORT-" + RID + ".txt",
                              "2026-11-03T02:47:43.674Z", FOLDER)
    return run, original, transfer


def test_real_timestamp_shape_is_plausible_not_authenticated():
    result = assess_run_report_chronology(*fixture(), expected_folder_id=FOLDER)
    assert result["chronology_consistent"]
    assert result["original_created_during_claimed_run"]
    assert result["transfer_created_after_original"]
    assert not result["muse_execution_authenticated"]
    assert not result["run_output_authorship_verified"]
    assert result["disposition"] == "HOLD_UNVERIFIED"


def test_outside_window_is_not_plausible():
    run, doc, txt = fixture()
    doc = replace(doc, created_at="2026-11-03T07:00:00+09:00")
    result = assess_run_report_chronology(run, doc, txt, expected_folder_id=FOLDER)
    assert not result["chronology_consistent"]
    assert not result["muse_execution_authenticated"]


def test_transfer_before_original_rejected_by_chronology():
    run, doc, txt = fixture()
    txt = replace(txt, created_at="2026-11-02T23:00:00+09:00")
    result = assess_run_report_chronology(run, doc, txt, expected_folder_id=FOLDER)
    assert not result["chronology_consistent"]


@pytest.mark.parametrize("mutator", [
    lambda r,d,t: (r,replace(d, title="MUSE-REPORT-REQ-20261101-003"),t),
    lambda r,d,t: (r,d,replace(t,file_id=d.file_id)),
    lambda r,d,t: (r,replace(d,folder_id="wrong"),t),
    lambda r,d,t: (replace(r,started_at="2026-11-03T09:38:00"),d,t),
    lambda r,d,t: (replace(r,finished_at="2026-11-03T08:00:00+09:00"),d,t),
])
def test_invalid_identity_or_window_fails_closed(mutator):
    args = mutator(*fixture())
    with pytest.raises(EvidenceError):
        assess_run_report_chronology(*args, expected_folder_id=FOLDER)
