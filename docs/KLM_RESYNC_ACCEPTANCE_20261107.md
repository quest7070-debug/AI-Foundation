# KLM Drive resync: no CURRENT before terminal Changes replay

**Parent:** Draft PR #283 at immutable source HEAD `b2d9bbb972cf8d6ae419e27d216916300689fe61`.
**Scope:** Source/read-only acceptance hardening only. Does not bind Drive tokens, install a scheduler, run a 9B model or modify Drive, HumanModel, Issue #35 or existing 9B worker.

## Defect reproduced

The preexisting `DriveState.finish_resync` returned `COMPLETE` and persisted
`klm_drive_cursors.status=CURRENT` as soon as a folder scan reported
COMPLETE, using the cursor from before the scan. This misrepresented actual
state if any Drive Changes happened during the scan, or if Changes replay
subsequently failed. Being fully inventoried is **not** being current.

The fixed eight-test M1 acceptance suite:
`tests/test_klm_drive_resync_acceptance.py` failed **5 tests and passed 3**
against exact parent logic at `711225d587d2e6a039c2a3c32d30fa91981c1071`.
Failures were premature `CURRENT` on scan finish, on network error after
scan finish, and on an unproven Changes page.

## Change

After a COMPLETE inventory, `finish_resync` now records
`(pre_scan_token, PENDING)` and returns `REPLAY_REQUIRED`.
Only `poll_changes` accepting the **final proven Changes page** may mark
that owner cursor `CURRENT` and advance it to `newStartPageToken`.
Transient failures preserve the original or intermediate `PENDING` cursor;
HTTP 410 requires a new full resync. Incomplete folder inventories do not
create an accepted cursor. The original test expectation is updated to
`REPLAY_REQUIRED`, rather than suppressing the test.

This source fix alone does not prove that a caller captured its pre-scan cursor
*before* fetching the actual folder snapshots; the separately authorized
M1/Drive owner adapter must independently prove that ordering. The current
connected Drive snapshots are PARTIAL (33 of 33), so no live scan has yet
reached this source gate. Do not use this change to assert production
readiness or continuous synchronization.

## Independent acceptance

Read-only real M1 isolated checkout of exact edited HEAD
`26a85420612bc39690e0f053be2cd739a2c217c3` ran:
`tests/test_klm_drive_resync_acceptance.py`,
`tests/test_klm_drive_input.py`, and
`tests/test_knowledge_lifecycle.py`: **98 tests passed in 1.56 s**,
no paid calls or inference. Full CI and independent PR readback remain
separate acceptance gates.

## Work boundary

Work should implement approved M1 Google Drive read-only credential binding,
full native pagination + pre-scan token/replay ordering, current Inbox source
version confirmation, existing 900-second scheduling and real unattended
cycle evidence. Work should branch from the updated stacked HEAD after
inspecting this fix; avoid concurrently changing `klm_drive_input.py` or
resync tests. Normal chat remains out of the path; development-approved
local 9B priority and actual compute lease cannot be bypassed.

**State:** SOURCE_ONLY_RESYNC_GATE_TESTED_NOT_DEPLOYED.
