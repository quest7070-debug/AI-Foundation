# Fixed runtime diagnosis through the existing M1 bridge

Scope: runtime-status, a separate fixed profile; triage remains unchanged.
Real M1 CI, main merge, runtime-status and fixed selftest accepted; see receipts below.

Exact owner-authored request:

Title: `Foundation M1 Bridge: runtime-status`

Body: `<!-- foundation-m1-bridge: {"version":1,"operation":"runtime-status"} -->`

The existing repository/owner/event/live-Issue identity gate, event-time trusted
checkout, bot-receipt deduplication and narrow token permissions are reused.
No caller-supplied path, command, parameter, restart or model request is accepted.

## Data sources and interpretation

- Fixed launchctl print probes distinguish gui/<uid>, user/<uid> and system
  for existing autodev, Operator, llama-swap and Homebrew Ollama labels.
  Each returns registration visibility, state, process presence, run count,
  interval and signed last exit code. Missing/inaccessible registration is
  UNAVAILABLE_OR_NOT_REGISTERED; an idle scheduled service is not an outage.
- Operator GET /v1/models is an implemented route in main's operator_server.py.
  Ollama /api/version and llama-swap /health retain the existing contracts.
  Only HTTP status is exported. An HTTP response is not full readiness.
- The fixed autodev LaunchAgent selects exactly one absolute owner-owned Python
  worker script, including an owner-renamed installed copy. Only its existing results/*.json,
  results/*.started and intake.json are inspected, with ownership, regular-file,
  no-leaf-symlink, permissions, size and scan bounds. Existing host-installed
  parent directory aliases are canonicalized before owner/mode checks; no
  request can choose a path. Installed worker code is never
  executed/imported. Existing worker/result contracts were checked against
  PR #268 head 3191a5bfec6be5bb5c28475c833a71755e736f41.
- Output contains allowlisted result/error codes, result counts, file-commit
  timestamps for latest start/result/success/failure, queued count and unfinished
  start count. Unknown exception prose, source paths, task IDs, feedback,
  delivery refs, model replies and raw logs are withheld. Exact timeout code and
  numeric HARNESS_EXIT code can identify a failing model turn/process.
- An unmatched start without a live registered worker returns RECONCILE_REQUIRED;
  it is never automatically retried. Last nonzero launchd exit is reported
  separately. SCHEDULED_IDLE describes process lifecycle, not job success.
- The existing canonical real-account-home compute.lock (PR #227) is opened
  read-only without O_CREAT. A transient nonblocking shared flock distinguishes
  EXCLUSIVE_HELD_AT_PROBE from AVAILABLE_AT_PROBE, then closes immediately.
  It never takes the compute-exclusive lease, changes contents or creates state.
  Availability is an instant observation, not admission or proof of idle hardware.
- Harness in this worker is an on-demand dsh CLI, not a required port-3081
  service. CLI process count and worker result evidence replace the port verdict.
- Kandev process counts are metadata only. Its supported Control MCP status,
  evidence and list_tasks remain the authoritative task/session observation
  path. No guessed Kandev HTTP health endpoint or duplicate lifecycle API is added.

## Fixed test execution and limits

Existing selftest now runs the two exact stdlib bridge/runtime-status suites,
each bounded to 35 seconds. No arbitrary test selector is accepted. Existing
Foundation CI supplies real M1 source regression before merge. The same Issue
receipt mechanism independently exposes post-merge selftest results.

No daemon, dependency, credential, routing configuration, scheduler or state
ledger is added. No raw log upload, service restart, model stop/switch, Native
operation, old193 resend or paid provider use is added. P2 recovery is deferred:
this bridge has no accepted restart authorization/lease/reconciliation contract.

Unsupported installation schemas, missing private files, stale/uncommitted
upstream state and services outside the fixed label set remain UNKNOWN or
UNAVAILABLE. Historical results do not establish a current process failure or
real 9B identity. Exact model identity, server-side timeout cancellation and
unload still require their existing domain-specific acceptance paths.

Desktop Commander calls for this change: zero. Read/edit/PR/CI/receipt work uses
GitHub; accepted Kandev task execution stays in the existing Control MCP.

## Next dependency reductions

1. Add a bounded current worker checkpoint to the existing worker only if live
   results show a gap in busy-defer/last-tick evidence; keep one existing source.
2. Add a Kandev health projection only after its version-matched native health
   contract is verified; use current MCP task evidence meanwhile.
3. Reuse existing Guard-owned recovery after exact approvals, lease, idempotency
   and post-recovery checks exist; do not invent a bridge restart subsystem.

## Independent real-M1 acceptance — 2026-11-07

Status: **ACCEPTED for fixed runtime-status diagnosis and fixed selftest**.

- Implementation PR #309, deployment-contract corrections #312 and #314.
- Final source head `e535d453ac42bb67c01f00913f45e602a1b993fd`; main merge `89a4523fc96ca0f94d63966a436cda3a35c6235e`.
- [Final real M1 CI #42371789730](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42371789730):
  SUCCESS, 1,683 passed, 15 skipped, 20 subtests; separate unittest runner 10 passed.
  Focused bridge/runtime suites: 17 + 12 tests. Source blobs independently read
  back equal reviewed contents; runtime blob b94a68b4e5e480f85979a5cde2ee850d220e2e2b.
- [Runtime Issue #315](https://github.com/quest7070-dev/AI-Foundation/issues/315#issuecomment-6706868208),
  [run #42372082289](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42372082289):
  SUCCESS on exact final main merge. Authenticated github-actions[bot] receipt
  independently read after execution.
- [Fixed selftest Issue #316](https://github.com/quest7070-dev/AI-Foundation/issues/316#issuecomment-6706871253),
  [run #42372083486](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42372083486):
  SUCCESS on the same merge, official receipt PASS, exit 0.
- Earlier Issues #310/#313 deliberately preserve initial unavailable observations.
  Their denial codes led to canonicalizing installed parent-directory aliases,
  binding the renamed owner-installed Python script from the fixed LaunchAgent,
  and matching the canonical lease's existing private lock-directory requirement.
  No host file permissions or services were changed to obtain results.

Live observations (snapshot only; not a new inference/development run):
- Operator /v1/models, Ollama /api/version and llama-swap /health: HTTP 200.
- Operator and llama-swap: running in gui/501; user/system observations separate.
- Autodev: SCHEDULED_IDLE, interval 300 seconds, 172 launches, last exit 0,
  queue 0, unfinished starts 0, invalid result files 0.
- Existing worker results: 4 DRAFT_PR_PRESENTED, 2 REPAIR_BUDGET_EXHAUSTED,
  2 UNKNOWN schemas retained as UNKNOWN, never promoted to success.
- Latest stored start 2026-11-07 14:42:45 JST; latest stored success
  14:37:43 JST; latest failure/result 14:58:11 JST, REPAIR_BUDGET_EXHAUSTED.
  These are file-commit timestamps, not a historical model-identity attestation.
- Existing compute lease: AVAILABLE_AT_PROBE, never an admission guarantee.
- Kandev: 2 named processes observed; existing Control MCP list_tasks also
  responded successfully. Task/session correctness still uses that native MCP.

No Desktop Commander calls, production restart, model stop/switch, Native signal,
old193 resend, paid provider call or model inference occurred in this work.
No new daemon, dependency, auth, router, scheduler or state ledger was introduced.

Remaining limits:
- Unknown result schemas/error prose remain hidden; current diagnostics expose
  only fixed codes, counters, timestamps and numeric Harness exit values.
- Busy defer has no durable last-tick reason in the existing worker contract;
  current intake, process/launchd state and live lease must be read together.
- Kandev full task/session state uses the existing MCP, not a new HTTP endpoint.
- Arbitrary host file extraction/GUI operations are unsupported by this bridge.
  There is no operation in this acceptance that required Desktop Commander;
  use it only after a concrete GitHub/MCP gap is demonstrated.
- Guard-approved restart/model lifecycle/Native recovery remains unimplemented
  here until exact approval, lease, deduplication and recovery readback exist.

Next extensions, in dependency-reduction order:
1. Project existing worker's fixed compiler/Harness failure codes and a bounded
   last-tick/busy-defer checkpoint, without uploading feedback or raw logs.
2. Reuse Kandev native task/evidence status in a bounded projection only if the
   existing Control MCP is unavailable to the caller.
3. Connect existing Guard recovery contracts after exact review and approval;
   retain the present read-only default.

## P0 diagnostic receipt completion — accepted update

The fixed profile now reads the existing worker's
`failures/autodev-<attempt>.json` classification receipt. It checks the exact
candidate schema, issue/attempt/result-status binding, non-reusable approval
flag and feedback SHA256 against the local result before projecting only a fixed
failure-class enum and stage. Existing classifier logic is not copied or executed.
Raw feedback, candidate task instructions, paths and source text stay on host.
Missing, stale, mismatched or unknown classification cannot establish a cause;
the known terminal result code is retained without guessing a root cause.

Existing `issue-N.claimed` records are bound to their exact attempt filename.
A claim with neither a start nor result now reports RECONCILE_REQUIRED, covering
a crash between the durable claim and start marker. No claim is removed/replayed.
Known candidate-publication receipt filenames are counted separately from
development attempts, preventing their CREATED/EXISTING states from appearing
as UNKNOWN development results.

This remains read-only diagnostic metadata on the existing transport. It does
not change the worker, install a checkpoint writer, dispatch a task or service,
acquire compute-exclusive authority, or reinterpret current intake as proof of
a historical busy-defer reason. The existing worker does not durably record that
reason; that gap remains explicit.

Focused regression: 17 bridge + 16 runtime tests passed. Real M1 source CI,
main merge, runtime-status and fixed selftest receipts are independently accepted below.

### P0 completion: independent final real-M1 readback

- PR [#319](https://github.com/quest7070-dev/AI-Foundation/pull/319):
  existing failure-receipt projection, pre-start orphan-claim detection and
  publication receipt separation; main `2f3fc179a4e38846a749d3600ac3791dd02f134e`.
- PR [#325](https://github.com/quest7070-dev/AI-Foundation/pull/325):
  exact existing host error-code prefixes for older installed results.
  Source head `6a93ffbd76bd33452b70663b98befa3b8ca44c7e`;
  final runtime main `6a55647476e7aa21cfc2f9dbd189cc47355772ba`.
- [Final real M1 CI #42373115565](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42373115565)
  SUCCESS: 1,687 passed, 15 skipped, 20 subtests; focused stdlib suites 33 passed.
  Runtime/test blobs independently read back equal reviewed source.
- [Issue #326 bot receipt](https://github.com/quest7070-dev/AI-Foundation/issues/326#issuecomment-6707045755),
  [run #42373369770](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42373369770):
  SUCCESS on the exact final runtime main.
  The latest stored failed development result now exposes
  **GENERATED_SOURCE_SYNTAX_ERROR** at **GENERATED_SOURCE_COMPILE**, from
  an exact host-result prefix; all following source/path/feedback remains private.
  Error counts: one GENERATED_SOURCE_SYNTAX_ERROR, one result reporting only
  REPAIR_BUDGET_EXHAUSTED. The latter is not promoted to a guessed root cause.
- [Issue #327 bot receipt](https://github.com/quest7070-dev/AI-Foundation/issues/327#issuecomment-6707050374),
  [run #42373370264](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42373370264):
  SUCCESS on the same runtime main; fixed selftest PASS, exit 0.
- Live orphan claims 0, unfinished starts 0, invalid records 0, queue 0;
  worker SCHEDULED_IDLE, 175 launches, exit 0, interval 300 seconds.
  Lease AVAILABLE_AT_PROBE; implemented service routes HTTP 200.
- No matching separate classification receipt was accepted in this snapshot;
  its exact identity/hash/privacy rejection behavior is fixture-tested.
  No known candidate-publication filenames occurred in this live snapshot
  (counter 0); the two existing UNKNOWN result schemas remain UNKNOWN.
- Busy-defer reasons are still not durably recorded by the installed worker.
  The bridge exposes current intake/lease/launchd state without inventing a
  historical reason. A future bounded checkpoint must be added by the existing
  worker owner, not by a new scheduler or state ledger.
- All operations remained fixed diagnostics or fixed tests. Desktop Commander,
  model inference, worker modification, service restart, host permission change,
  new credentials, Native/old193 signals and paid provider calls: zero.
