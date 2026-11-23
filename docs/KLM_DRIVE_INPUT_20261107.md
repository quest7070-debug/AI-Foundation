# Drive-first KLM input and development-idle handoff

Parent: Draft #279 `feat/knowledge-lifecycle-readonly-core-20261107`.
Start parent SHA: `d78e927279cbfc667b0909f2f72431120f1a6fc3`.
Implementation child branch: `feat/klm-drive-intake-idle-20261107`.
Issue #278; design #277's later scheduling amendment was read independently of
the older design snapshot inherited by #279. No parent core/test modifications.

## Implemented path

`klm_drive_input.py` provides an injected GET-only native Drive adapter, complete
page and recursive folder traversal, page receipts/checkpoints, safe restart,
same-scan revision-conflict detection and explicit COMPLETE/PARTIAL/UNKNOWN.
The optional Changes path preserves per-owner-scope tokens, handles HTTP 410,
requires complete resync with a pre-scan token, bounds authorized IDs, and
reports removed-or-inaccessible rather than claiming deletion. Unknown new IDs
request scope-limited rescan. It never uses account-wide events to enlarge scope.

`klm_drive_runtime.py` contains the read-only authorized HTTP port, actual
connector-capture adapter, deterministic metadata checks and capture-to-work
composition. HTTP is GET-only to fixed Google API paths, no redirects/proxies,
explicit token provider, ten-second timeout and bounded response bytes. No token
is supplied or extracted in this change. Connected tool availability supports
metadata polling, not Changes or a provably complete all-MIME paginated list.

`klm_drive_work.py` reads existing Inbox headers without modifying them. A legacy
row is content-identified (not silently assigned a stable row ID); identical rows
and reordering are idempotent. Editing a legacy row creates a different unresolved
record, because correlation cannot be proven. Explicit-ID rows support revision
replacement. Persist only owner/scope/ID/revision/hash/row hint/result pointers,
never raw row text. Source pointer and existing work_steps are created atomically
in the same existing Durable Work DB. No second task DB or scheduler is added.

Intake and revision detection do not need inference. A new invocation can continue
the durable scan and pending records. Source corrections cancel old unstarted
explicit-ID work; a changed source during handling cannot be marked verified.
Crashes leave RUNNING claims for independent reconciliation, not automatic retry.
Failed handlers remain failed. Pending count, oldest age and uncertain-running
count are observable without altering development priority.

## Existing worker/lease composition

The worker code was reconciled against Draft #268
`3191a5bfec6be5bb5c28475c833a71755e736f41` and #248
`eeb584a2d488de94c25c1836a36c0328e61bca0f`. Installed M1 entry is
`local9b-autodev/worker.py`, invoked by the existing 300-second LaunchAgent.
Do not modify these files. Their host lease module is installed separately and
is absent from #279's source tree; no duplicate lease implementation is added.

`read_development_state` calls the existing Issue bridge/policy in read-only mode,
not its queue-mutating collect_ready. It checks currently approved unconsumed
Issues, started/claimed/result receipts and unknown/malformed states. Actual
worker success is `DRAFT_PR_PRESENTED` + delivery_ref + source SHA, not an invented
completion label. Unverified writes/STOPPED/missing results defer; known bounded
non-publication terminal outcomes remain separately terminal.

`IdleKlmWorker` accepts the installed HostComputeLease object and its busy/error
types from its host. It rechecks fresh development observations under that exact
lease, checks real compute occupancy, rechecks before an atomic existing-work
claim, and processes one item. Occupancy/lease failure defers rather than starting
or killing a model. No approved development Issue is generated from a Drive row.
A development Issue arriving after an inference actually starts waits for that
bounded item; recheck prevents another KLM item from starting ahead of it.

The bounded host handler is **UNBOUND by default**. `klm_proposals` delegates
exact source spans to #279's decompose_batch; it does not recreate meaning logic
or invoke a model. The deadline is propagated and a late result is refused.
A future real inference handler must enforce that deadline in its existing local
request port; this synchronous adapter cannot safely stop an arbitrary callback.
Until that port is independently accepted, there is no real 9B KLM execution.
No model load, alternate model, cloud fallback or background inference is added.

## Live connected Drive observation

Five user-specified roots, **33 observed folders / 109 child objects** (28 nested
folders, 81 files); all 109 child metadata records were independently fetched.
No audio/private source bodies were read. Explicit Inbox read covered A1:L100
(allocated grid verified as 100 rows), with 6 nonempty data rows. Its second read
matched the first. Operator-document metadata and parent were independently read
twice and matched using metadata SHA; native content revision/ETag was not exposed
by the normalized connector even when requested. This is METADATA_ONLY evidence.

All 33 listing receipts remain **PARTIAL**, 0 COMPLETE, 0 failed reads. The bounded
list_folder connector exposes no provider page token/terminal-page proof. Zero
returned items are therefore not proof of an empty folder. We do not claim all
Drive contents were inventoried or that intermediate events/deletions are known.
The native GET adapter supports proper paging when approved credentials become
available, but that capability is only contract-tested here.

Actual capture -> Durable Work: 6 pointers staged, restart replay 0 new / 6
duplicates. No existing Inbox row or other Drive file was updated. Detailed
metadata belongs only in the existing private Drive audit folder; GitHub evidence
contains counts, hashes and explicitly needed operator/ledger references.

Deterministic findings: 109 native revision identifiers unavailable; two groups
of identical folder names are review candidates, not content duplicates; six
Inbox source references have no native URL/ID and require owner/source binding.
The Drive operator plan still says KLM is design-only while #279 has accepted
source-only code. Proposed correction is progress-only: deployment is NOT implied.
Ten files directly in the named September technical archive are historical
reference candidates by the existing placement rule. No automatic move, deletion,
permission change or HumanModel decision promotion is performed.

## Execution / acceptance

Run `PYTHONPATH=src python scripts/klm_drive_readonly_tick.py --capture OWNER_PRIVATE_CAPTURE
--work-db EXISTING_DURABLE_WORK_DB --report PRIVATE_OR_AGGREGATE_REPORT` manually.
The input is a connector-generated receipt, not arbitrary model text. The native
read-only HTTP port instead needs an existing explicitly approved token provider.
This CLI has no automatic schedule installation or inference flag.

Focused tests cover paging, recursive traversal, UNKNOWN/PARTIAL, expired cursor,
resync, revision conflicts, dedup/restart, communication failure, limited deletion
knowledge, read-only transport, dev-active/unknown/stale states, shared-lease busy,
post-idle races, one claimed item, source update before/during processing, uncertain
claim recovery, backlog age, failure/no-input and no-effect #279 handoff.
M1 and CI evidence are recorded separately after their actual completion.

## Still unaccepted / next implementation

1. Host-owned Drive credentials for continuous full-list/Changes access and a
   complete initial resync. Current connector snapshots cannot certify completeness.
2. Stable explicit Inbox IDs/source URLs as a reviewed update plan; legacy rows
   remain content-only identities. Automatic row writes stay disabled.
3. A separately reviewed bounded existing-9B inference handler, source readback,
   real dev-idle acceptance and subsequent development-priority check.
4. Existing-scheduler registration for 900-second metadata ticks, stop/restart and
   multiple unattended M1 cycles. **No constant unattended operation is accepted.**
5. Owner-authorized retention/cleanup integration before increasing history caps.
   No prune of uncertain claims and no priority inversion to reduce backlog.

HumanModel #273/#274/#276, local9b #248/#268 and Native #35 remain untouched.


## Actual M1 acceptance checkpoint

Final code `2a10560a069bbf2be58df642495fab55dee8c094` fetched by immutable SHA;
every fetched file matched its independent Git blob. **90 tests passed** (36 new,
54 unchanged #279 tests). Six actual connector-derived Inbox pointers persisted
in an isolated M1 acceptance DB using SQLiteWorkStore; reopening the store added
zero pointers and recognized six duplicates. This is not a new production queue.

The live approved-development observer found one pending Issue, zero unresolved
worker starts/results and complete API coverage. The real installed lease was
acquired/released without inference, but that did not override development
priority: the final-code worker recorded **WAIT_DEV_IDLE**, including a durable
last-attempt timestamp; neither source processing nor model handler was called.
The earlier code checkpoint also exercised the same installed lease class across
two processes on an isolated test lock and observed DEFER_COMPUTE_BUSY.

Independent M1 file readback: `docs/evidence/KLM_DRIVE_INPUT_M1_FINAL_20261107.json`;
earlier cross-process lease receipt: `KLM_DRIVE_INPUT_M1_20261107.json` in the same
evidence directory. No live Drive credential provider, schedule or model handler
was bound on M1. Real 9B KLM inference and unattended operation are NOT ACCEPTED.

Foundation CI: run 42348877711; P02 inventory: run 42348877674. Their terminal
results are reported in the PR separately. Later documentation-only evidence
commits do not change the validated code/test blobs.


`read_inbox_source` is the concrete current-source resolver over the approved
Sheets read port. It derives row identity from fresh cells rather than a saved
row number, refuses foreign source IDs, verifies the allocated-grid bound, and
preserves populated cells beyond the header. Source raw bytes must independently
match SHA256 before the worker invokes its handler. All six real rows were
resolved against a third authenticated Inbox read, with exact hash/revision
agreement. Public evidence contains only their pointer identities/hashes in
`docs/evidence/KLM_INBOX_SOURCE_READBACK_20261107.json`.

API contracts were checked against Google's primary documentation:
[files.list](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list)
and [changes.list](https://developers.google.com/workspace/drive/api/reference/rest/v3/changes/list).
No connected-tool Changes support or native-version readback is inferred from
these documentation pages.


Final immutable source CI [42348877711](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42348877711)
completed successfully: **1,722 passed, 15 skipped**; compile, Cedar and external
storage synthetic-mount contracts passed. P02 inventory [42348877674](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42348877674)
also completed successfully. This validates source, not deployment or unattended
operation. Parent #279 was independently re-read unchanged at the starting SHA.

New private Drive artifacts and parent/share readback are recorded in
`docs/evidence/KLM_DRIVE_ARTIFACT_READBACK_20261107.json`. They include the detailed
metadata audit in 04, operator progress in 05, and final immutable-source M1/row
acceptance receipt in 04. Existing Inbox rows/files/permissions were not changed.
The initial progress artifact records its earlier 86-test checkpoint; the final
source acceptance artifact records the later 90-test checkpoint. No source
original or personal Raw was exported to GitHub.
