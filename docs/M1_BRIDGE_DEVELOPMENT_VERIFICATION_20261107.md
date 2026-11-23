# Desktop Commander-independent verification and installed-source inspection

This extends the accepted M1 bridge with two fixed operations. Real M1 CI,
main integration, live operation receipts and independent readback are accepted below.

## Exact owner-authored requests

1. Title: `Foundation M1 Bridge: source-status`
   Body: `<!-- foundation-m1-bridge: {"version":1,"operation":"source-status"} -->`
2. Title: `Foundation M1 Bridge: verify-main`
   Body: `<!-- foundation-m1-bridge: {"version":1,"operation":"verify-main"} -->`

Both reuse the existing exact repository/owner/original-event/live-Issue checks,
duplicate-key refusal, bounded API responses and authenticated bot-receipt replay
protection. No request can select a command, branch, file, host path or test.

## Installed-source status

The existing autodev LaunchAgent selects one owner-owned Python worker. Reuse its
validated path and inspect only the fixed worker/helper/module allowlist in
`SOURCE_FILES`. Each regular owner-owned, non-writable-by-others file is bounded
to 256 KiB; leaf links are refused and existing parent aliases are canonicalized.
Return only fixed component labels, SHA256, byte count and file commit time.
Missing or untrusted files remain UNAVAILABLE. No source contents, actual paths,
Git remotes, arguments, model output, credentials or private config are returned.

This permits independent comparison with reviewed GitHub source without remote
terminal/file access. A hash is not proof of loaded process identity, deployment
approval or semantic correctness. It does not modify installed code or services.

## Existing CI as the verification owner

`verify-main` enters the existing `.github/workflows/ci.yml` unit job. It does
not create another test engine or scheduler. The event-time trusted main SHA is
checked out explicitly; no Issue-selected branch or PR code is executed.

Before environment sync or tests, the stdlib bridge preflight validates the
fresh Issue and exact workflow/job identity, compares actual checkout HEAD to
GITHUB_SHA, and refuses replay. The existing pinned uv/frozen dependency sync,
compile, Cedar checks, default pytest suite and synthetic ledger contracts run
unchanged. No new dependency or paid provider is introduced. Test/cache writes
are confined to the existing CI execution model; this is not a production
service or model execution operation.

The unit job has only contents:read and issues:read. A separate bounded receipt
job, dependent on its actual result, is the sole issues:write owner. It checks
out the same trusted source and revalidates the live Issue. Only `success` can
produce PASS; failure/cancelled/skipped become FAIL when the receipt job runs.
The receipt contains the exact source SHA, CI outcome, operation and run ID;
unit output and exceptions are not copied into the Issue. Cancellation that
prevents receipt-job scheduling cannot be called complete: inspect Actions.

Verification concurrency is per Issue and does not cancel normal main/PR CI.
Existing push/PR/manual CI behavior is retained. A replayed preflight fails closed
before environment/test execution; a repeated receipt is read-only/idempotent.

## Complete ordinary development route

- GitHub connector: source read/edit, commits, PR review and approved merge.
- Existing Kandev Control MCP: supported task submission, state, evidence,
  continuation and individual human gates; do not duplicate those lifecycle APIs.
- M1 bridge: host/runtime/KLM diagnostics, installed source fingerprints,
  bridge selftest and fixed trusted-main CI execution with independent receipts.
- Existing Guard/release owner: production authority and recovery contracts.

Arbitrary host file writes, shell, GUI/RPA, service restarts, model stop/switch
and Native effects are not introduced. In particular, neither an available lease
nor a matching source hash authorizes a restart or deployment. The previous
old193/no-paid-provider constraints remain unchanged.

The bridge requires its existing self-hosted runner. If all accepted remote
control paths are offline, initial OS/network/runner recovery still requires a
separate working host-access path or local intervention. Do not claim queued
verification or observed metadata as completed recovery.

Focused validation: 23 bridge + 18 runtime tests passed; workflow YAML parsed.
Real M1 and post-merge receipts below close live acceptance.

## Independent real-M1 acceptance — 2026-11-07

Decision: **ACCEPTED — installed-source inspection and fixed trusted-main verification**.

- Implementation [PR #329](https://github.com/quest7070-dev/AI-Foundation/pull/329).
  Reviewed source `6539dc64913a6759427376747282b276d8c8c0bc`;
  runtime main `11b631bdd9a86d1b27857f5cf3f417e9ca6d117f`.
- [PR real M1 CI #42374315217](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42374315217)
  SUCCESS: 1,695 passed, 15 skipped, 24 subtests; separate ledger runner 10 passed.
  Focused bridge/runtime suites 23 + 18 = 41 passed. Python/YAML/whitespace checks
  passed and changed source/workflow blobs independently matched reviewed content.
- [Source Issue #330 official bot receipt](https://github.com/quest7070-dev/AI-Foundation/issues/330#issuecomment-6707211343),
  [run #42374565997](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42374565997):
  SUCCESS on the same runtime main. Eight fixed installed components observed;
  failure_intake UNAVAILABLE, without inferring missing versus untrusted.
  Worker SHA256 `9b4fd0c89da931b9c242c102b7777c0a1ec95e49a16eb016b06a1f41703b95c0` independently matched
  GitHub `scripts/local9b_autodev_worker.py` at the previously recorded install
  source `5c68d8da467def47ec1346c05ef400e40793925d`.
  This proves file equality, not in-memory process identity or deployment authority.
- [Verification Issue #331 official bot receipt](https://github.com/quest7070-dev/AI-Foundation/issues/331#issuecomment-6707260399),
  [run #42374566253](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42374566253):
  SUCCESS, actual unit job + separate receipt job both succeeded. Fresh exact
  request and checkout preflight succeeded before environment sync. Existing
  pytest: 1,695 passed, 15 skipped, 24 subtests; separate ledger 10 passed.
  Receipt PASS/ci_outcome=success/source_sha=11b631bdd9a86d1b27857f5cf3f417e9ca6d117f.
  Actions result, job steps/log summary and authenticated bot receipt were
  independently read back; queueing was not claimed as completion.
- Existing Kandev Control MCP usage rules and Development task enumeration
  were read successfully. Its task/session/approval ownership is unchanged;
  no duplicate task executor, route or lifecycle ledger was introduced.

### Practical Desktop Commander replacement

Ordinary Foundation source edits/PRs use GitHub. Host/runtime diagnostics and
installed-code fingerprints use the M1 bridge. A fresh verify-main Issue now
runs the existing fixed CI on trusted main and returns an independent official
receipt without a desktop/terminal action. Kandev's supported development
task/status/evidence/human-gate controls remain its existing MCP interface.
None of these accepted operations needs Desktop Commander.

No Desktop Commander call, new provider/auth/dependency, host permission change,
production service restart, model stop/switch/inference, Native/old193 signal or
new runtime daemon/scheduler was used for this change. The verify operation
explicitly uses existing CI checkout/environment/test/cache writes; it is not
described as a host-read-only observation.

### Remaining boundaries

- No arbitrary shell, arbitrary private file extraction, GUI/RPA, or unreviewed
  branch/test selection is provided. Use repository changes and the existing
  Kandev/Guard contracts for authorized development and release operations.
- Production recovery still requires its exact Guard/release approval,
  lease/deduplication and independent readback; this does not authorize it.
- Host/network/runner bootstrap and physical/GUI recovery cannot be performed
  by an offline runner. A separate supported host-access path or local
  intervention remains necessary when all accepted remote paths are offline.
- Cancellation may prevent receipt scheduling. Read Actions as the execution
  authority in that case; do not infer PASS from absence of a receipt.
