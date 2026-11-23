"""A completed Drive inventory is NOT a replayed Drive Changes cursor.

Real native pagination/credentials and the 900-second scheduler remain in Work's
scope. These tests are synthetic, no M1 credential or external Drive mutation.
"""
from types import SimpleNamespace

import pytest

from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.klm_drive_input import DriveState, Page, CursorExpired


@pytest.fixture
def ready_scan(tmp_path):
    s = DriveState(SQLiteWorkStore(tmp_path / "work.sqlite"))
    scan = s.begin_scan(["approved-root"], scan_id="exact-scan")
    source = SimpleNamespace(list_children=lambda folder, cursor=None: Page(tuple()))
    receipt = s.scan(source, scan)
    assert receipt["coverage"] == "COMPLETE"
    return s, scan


def cursor(s):
    with s.db() as db:
        row = db.execute("SELECT token,status FROM klm_drive_cursors WHERE owner_scope=?",
                         ("bound-owner",)).fetchone()
    return tuple(row) if row else None


def test_full_inventory_cannot_promote_changes_to_current(ready_scan):
    state, scan = ready_scan
    result = state.finish_resync(None, "bound-owner", scan, start_cursor="pre-scan-token")
    assert result == "REPLAY_REQUIRED"
    assert cursor(state) == ("pre-scan-token", "PENDING")


def test_empty_change_replay_is_the_first_valid_current_transition(ready_scan):
    state, scan = ready_scan
    state.finish_resync(None, "bound-owner", scan, start_cursor="before")
    assert cursor(state)[1] == "PENDING"
    api = SimpleNamespace(changes=lambda token: Page(tuple(), new_start_cursor="after"))
    assert state.poll_changes(api, "bound-owner", set()) == "COMPLETE"
    assert cursor(state) == ("after", "CURRENT")


def test_network_error_after_complete_inventory_cannot_claim_current(ready_scan):
    state, scan = ready_scan
    state.finish_resync(None, "bound-owner", scan, start_cursor="before")
    api = SimpleNamespace(changes=lambda token: (_ for _ in ()).throw(OSError("offline")))
    assert state.poll_changes(api, "bound-owner", set()) == "PARTIAL"
    assert cursor(state) == ("before", "PENDING")


def test_cursor_expiration_after_complete_inventory_demotes_to_rescan(ready_scan):
    state, scan = ready_scan
    state.finish_resync(None, "bound-owner", scan, start_cursor="before")
    api = SimpleNamespace(changes=lambda token: (_ for _ in ()).throw(CursorExpired()))
    assert state.poll_changes(api, "bound-owner", set()) == "RESCAN_REQUIRED"
    assert cursor(state) == ("before", "RESCAN_REQUIRED")


def test_incomplete_page_does_not_promote_terminal_changes_state(ready_scan):
    state, scan = ready_scan
    state.finish_resync(None, "bound-owner", scan, start_cursor="before")
    api = SimpleNamespace(changes=lambda token: Page(tuple(), terminal_proven=False))
    assert state.poll_changes(api, "bound-owner", set()) == "PARTIAL"
    assert cursor(state) == ("before", "PENDING")


def test_interrupted_pagination_remains_pending_until_terminal_page(ready_scan):
    state, scan = ready_scan
    state.finish_resync(None, "bound-owner", scan, start_cursor="before")
    api = SimpleNamespace(changes=lambda token: Page(tuple(), next_cursor="p2") if token=="before"
                          else Page(tuple(), new_start_cursor="new-start"))
    assert state.poll_changes(api, "bound-owner", set(), page_budget=1) == "PARTIAL"
    assert cursor(state) == ("p2", "PENDING")
    assert state.poll_changes(api, "bound-owner", set()) == "COMPLETE"
    assert cursor(state) == ("new-start", "CURRENT")


def test_incomplete_inventory_never_creates_current_cursor(tmp_path):
    s = DriveState(SQLiteWorkStore(tmp_path / "state.sqlite"))
    scan = s.begin_scan(["root"])
    api = SimpleNamespace(list_children=lambda folder, cursor=None: Page(tuple(), terminal_proven=False))
    assert s.scan(api, scan)["coverage"] == "PARTIAL"
    assert s.finish_resync(None, "bound-owner", scan, start_cursor="before") == "PARTIAL"
    assert cursor(s) is None


def test_failed_changes_replay_is_still_not_production_approval(ready_scan):
    state, scan = ready_scan
    assert state.finish_resync(None, "bound-owner", scan, start_cursor="before") == "REPLAY_REQUIRED"
    # A completed rescan alone is insufficient to certify the credential,
    # approved inbox owner, scheduler, model handler or local9B priority policy.
    assert cursor(state)[1] != "CURRENT"
