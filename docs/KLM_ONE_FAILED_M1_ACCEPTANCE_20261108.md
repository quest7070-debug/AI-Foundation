# KLM historical FAILED acceptance — fixed one-item owner command

The existing read-only M1 bridge remains read-only. The GitHub Actions workflow `Foundation KLM single failed recovery` is a temporary, exact-one-operation capability to inspect/revalidate/retry **one oldest historical FAILED KLM Inbox item** through the already installed local 9B and existing KLM Durable Work. The fixed release is `369e74a4f8a9f19f369aa182f865b2d8fadb57c0` from Draft PR #301, with M1 source CI #42405312687 SUCCESS (1,793 passed).

**No Kandev, Desktop Commander, new scheduler, new model, new credentials, Guard, Native, Operator or owner writes.** The only mutable host data is the existing KLM Work step and receipt journal for the selected failed item. The stored original is read through the existing owner-bound read-only Inbox adapter, revision/bytes/SHA are verified, previous failure history is preserved, and existing development priority and HostComputeLease are enforced by the official IdleKlmWorker. Only the one item is allowed to be retried. If the previous exact failure is already recorded, return `REPEATED_FAILURE_REVIEW_REQUIRED` without a retry. If development or shared compute is busy, stop/defer. Never change the global model route, bypass an old uncertain RUNNING claim, disclose raw data or output model text.

**Authorization:** Only one trusted owner-authored Issue with exact title `Foundation KLM one failed recovery: 369e74a4` and exact body `<!-- foundation-klm-recovery: {"version":1,"release":"369e74a4f8a9f19f369aa182f865b2d8fadb57c0","operation":"oldest-failed-once","effects":"klm-no-owner-write"} -->`. Validate event and independently reread its live state and previous GitHub bot receipts. This request contains no path, shell command, source ID, model choice or credentials. The code checks the pinned installed SHA plus six source blobs, correct KLM LaunchAgent, no active job, owner-only host configuration, source revision and exact current bytes.

**Acceptance:** A fixed metadata-only GitHub bot receipt records before/after counts for Work, atoms, relation reviews, placements and source revision verified status. Synthetic tests validate owner/replay/host rejection and no-source-content publication. A 9B JSON response or Work's status alone cannot prove semantic truth: later independent human-labeled semantic checks remain necessary.

This workflow must be removed after its one-shot result is recorded and independently checked. If it cannot safely complete, report the exact fixed failure code; do not widen the bridge, change KLM scheduler, requeue all FAILED entries or silently retry.


## Replacement recovery transport (2026-11-08)

Real M1 Issues #381, #382 and #388 all timed out/cancelled after three minutes.
Stage traces on #388 prove `LIVE_OWNER_VALIDATED`, `M1_RELEASE_CHECK`,
`DEV_IDLE_CHECK`, `DB_CHECK`, then stalled at `SOURCE_READ_BEGIN`.
The specific Keychain-vs-network delay is not yet independently distinguished.
A runner must not prompt/load an owner GUI Keychain secret or call Google
Sheets directly for this recovery.

The same strict owner-only one-item Issue now **stages one Durable Work
`klm-retry-intent:<intake-id>`** into the existing private Work DB. This stage
does not call Google or 9B, and never changes original FAILED status. A later
existing 900-second GUI-host KLM tick claims that intent, freshly reads the
approved Inbox through its existing proven OAuth context, checks exact
revision/SHA/bytes, calls the existing single-entry history-preserving
`IntakeQueue.requeue_failed` (which rereads the bytes), and only then
publishes the verified intent outcome. The ordinary KLM worker obtains the
existing compute lease and performs 9B when admitted. A lost/uncertain
RUNNING claim is never silently replayed.

This contract is **not deployed** until a new KLM release containing the
host-side intent consumer is independently validated and SHA-pinned.
Issue receipts showing STAGED alone are never evidence of original
requeue or of model inference. No other owner or Native/Guard effect is granted.
