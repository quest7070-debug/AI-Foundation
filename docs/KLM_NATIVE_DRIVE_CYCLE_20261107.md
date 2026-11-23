# KLM native Drive/Inbox polling callback (2026-11-07)

Parent: PR #284 at `a4f0606d553b27b16a1ad4f890782a3900810850`.
This child supplies a runnable host callback, not deployment acceptance.

## Behavior

`NativeDriveCycle.tick()` composes the existing Drive scanner, Changes replay,
Inbox pointer intake and optional IdleKlmWorker. The caller supplies an already
approved Drive GET port, exact existing Inbox Sheets GET port, five approved roots,
owner identity and existing Durable Work store. The optional idle worker uses
the installed HostComputeLease for inference.
No credentials are discovered or copied from the ChatGPT connector.

The durable `klm_drive_native_cycle` checkpoint lives in the existing work DB:
scope hash, scan ID, pre-scan Changes token, last attempt and last successful
terminal replay time. At most 32 scope histories; existing scan/event/intake caps
remain unchanged. Tokens/metadata remain owner-private, never GitHub output.
Attempts are at least 900 seconds apart, including failed requests. Existing
Durable Work claims serialize overlapping metadata callbacks; an interrupted
RUNNING claim requires reconciliation before further polling. Clock regression defers. No timer/thread/LaunchAgent,
second queue or second execution DB is created.

Initial/resync polling captures and persists a Changes token before scanning.
Pagination and the replay cursor survive reconstruction of the callback. The
#284 REPLAY_REQUIRED contract is checked; only a fresh terminal Changes replay
returns CURRENT. A previously CURRENT token is marked PENDING before a new
poll so failure cannot preserve fresh-current evidence. Unknown IDs/410 request
a new scan within the same roots, without ingesting out-of-scope metadata.
Inconsistent scan revisions/repeated cursors restart on the next due tick.

Inbox grid dimensions are read independently on every fetch. The exact existing
Inbox is bounded to 1000 rows/12 columns; grid growth beyond the bounds refuses
to accept a truncated prefix. Fresh original cells are resolved again before
and after the existing worker handles a pointer. Only pointer/hash data enter
Durable Work. OwnerInboxHTTP uses GET on the fixed Sheets origin and exact
Inbox paths; redirects/proxies disabled and original bounded HTTP behavior reused.

Metadata network I/O does not acquire the compute lease, so it cannot hold up
development while waiting for Drive. The existing Durable Work polling claim is
released before the optional IdleKlmWorker runs. That worker is called only after CURRENT and
still owns all development-first rechecks and the maximum 120-second item limit.
The native callback has no model implementation, does not start a daemon and
does not relax the separate requirement that a real handler enforce its deadline.

## Existing-host composition

```python
from ai_foundation.klm_drive_cycle import NativeDriveCycle, NativeInboxReader
from ai_foundation.klm_drive_input import DriveState, ReadOnlyDriveAPI
from ai_foundation.klm_drive_runtime import OwnerDriveHTTP, OwnerInboxHTTP

# All arguments below must come from existing, owner-approved host bindings.
cycle = NativeDriveCycle(
    DriveState(existing_work_store), roots=approved_root_ids,
    owner_scope=approved_owner_scope,
    drive=ReadOnlyDriveAPI(OwnerDriveHTTP(approved_drive_token_provider)),
    inbox=NativeInboxReader(OwnerInboxHTTP(approved_sheets_token_provider)),
)
# Called by the existing scheduler; this does not register a schedule.
report = cycle.tick(worker=existing_idle_worker, handler=approved_bounded_9b_handler)
```

## Validation and remaining live prerequisites

15 focused tests cover multi-cycle/restart/dedup, partial list/replay resumption,
410/out-of-scope resync, conflicting scans, stale CURRENT invalidation, overlapping/interrupted sync claims,
metadata polling during busy compute, worker invocation after claim release, exact Inbox source changes, grid growth,
fixed Sheets HTTP origin and clock regression. Tests use native-shaped synthetic
ports and an isolated work DB; they are not authenticated live Drive evidence.
Local standard-library unittest passed. Real-M1 tests/CI are recorded separately
only after completion.

Read-only inspection of M1 Foundation config found no explicit Drive/Sheets host
binding (top-level config contains paths/toolhive/schema keys; no configured
Google/Drive credential filename under the inspected Foundation state).
The existing local9b worker owns a temporary Ollama lifecycle for development;
there is no approved reusable bounded KLM handler exposed to this callback.
Neither fact is solved by reusing connector credentials or changing that worker.

Remaining: provision explicit approved native Drive/Sheets token providers;
perform all-page live resync plus terminal Changes replay; expose/review the
existing 9B provider lifecycle and deadline enforcement for KLM; then register
this callback with the existing scheduler and observe multiple actual unattended
900-second cycles. No production activation or main merge is claimed.

Google API contracts: [spreadsheet metadata](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/get)
and [values GET](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/get).

## Exact real-M1 source acceptance

Immutable code `123ffa37e49e7ed1eca42100a52a37cef3928e24` passed **113 focused tests**, plus 2 subtests, on an isolated M1 checkout. New code/test Git blobs were independently fetched from GitHub and matched the exact checkout; protected parent meaning-core/test blobs are unchanged. Parent #284 was independently read back unchanged.

[Foundation CI #42351271753](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42351271753) **SUCCESS: 1,745 passed / 15 skipped / 1 warning / 2 subtests passed** (137.51 seconds), including compile, Cedar and external SSD synthetic-mount contracts. [P02 inventory #42351271760](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42351271760) also SUCCESS.

Receipt: `docs/evidence/KLM_NATIVE_DRIVE_CYCLE_M1_20261107.json`.
**Decision: SOURCE_ONLY_NATIVE_CALLBACK_NOT_DEPLOYED.** Native Drive/Sheets auth, real 9B KLM handling and scheduler registration remain unbound; no authenticated unattended cycle or complete live Drive inventory is claimed. The later evidence-only commit does not change the validated code/test blobs.
