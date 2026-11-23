# Operator and installed-storage status through the existing M1 bridge

Accepted on real M1. Existing main/PR/Actions and official accepted receipts were
checked before extension; CI, main integration and live official readback are
recorded below.

## Exact requests

- Title: `Foundation M1 Bridge: operator-status`
  Body: `<!-- foundation-m1-bridge: {"version":1,"operation":"operator-status"} -->`
- Title: `Foundation M1 Bridge: storage-status`
  Body: `<!-- foundation-m1-bridge: {"version":1,"operation":"storage-status"} -->`

Both use the accepted owner/repository/original-event/live-Issue/deduplication
checks and trusted event-time main checkout. No caller-selected URL, file path,
command, service, branch or diagnostic selector is accepted.

## Operator internal observation

Use the existing official read-only GET `127.0.0.1:8766/api/human` contract from
operator_server.py, human_view.py and human_operations.py. Never scrape its UI,
read Guard SQLite directly or call approve/cancel/reconcile/credential endpoints.
Direct HTTPConnection avoids proxy environment/redirect routing. Timeout is
three seconds, response at most 256 KiB, rows at most 2,000 per field. Invalid,
duplicate-key, oversized or incompatible data returns explicit UNAVAILABLE.

Project only fixed status/function enums, numeric window counts and validated
timestamps: server-reported Operator state; notices needing action/input; task
status counts; active capability counts and oldest start; service reported
availability counts; provider/route counts. Unknown strings become UNKNOWN.
Task text/results, notice detail, source/subject/job IDs, provider bindings,
credential data and original response bodies never leave the host.

Coverage is explicitly OPERATOR_API_WINDOW_ONLY. The API presents a bounded
human/UI view, not the complete durable Guard/Work inventory. Its READY state
is not independent service readiness or authority to retry an uncertain effect.
No separate task/status ledger, health authority or execution engine is created.

## Real runtime storage and log metadata

Use statvfs/stat for fixed system and owner-home targets and the existing
LaunchAgent-bound installed-worker directory. Return capacity/available GiB,
read-only flag when supported and anonymous filesystem grouping. No directory
walk, du command, model admission threshold, write test or cleanup is performed.
Anonymous filesystem groups do not identify physical drives or APFS shared
container capacity; do not sum them as independent physical disk capacities.

For the existing fixed autodev/Operator/llama-swap LaunchAgent labels, reuse
their owner-owned non-writable-by-others plist to select StandardOutPath and
StandardErrorPath. Inspect only regular owner-owned log stat metadata: byte
count and modification time. Refuse leaf symlinks and untrusted permissions;
canonicalize existing parent aliases. Never open/read log contents, return real
paths, hash private log data, truncate/delete a file or change its permissions.
Unavailable metadata remains UNAVAILABLE, not an inferred missing file/outage.

This supplies runtime-volume free-space and log-growth evidence independently
of the runner checkout's free space. Recovery still belongs to existing Guard
and service/release owners; no restart, approval, stop, cleanup, Native/old193
signal or model/provider call is added or executed by these operations.

## Verification

The existing selftest now runs three exact stdlib suites (bridge, runtime,
Operator), each bounded to 35 seconds. Local focused tests: 23 + 21 + 6 = 50
PASS. Source has no added dependency/auth/daemon/router/scheduler/state ledger.

Real M1 CI and independent live receipts are recorded below.

## Independent real-M1 acceptance — 2026-11-07

Decision: **ACCEPTED for fixed Operator API and storage/log-metadata observations**.

- [PR #333](https://github.com/quest7070-dev/AI-Foundation/pull/333);
  reviewed source `87ef8427ce68aa0b8e5e9edfcf35480852351d04`;
  runtime main `c445bfd6c57202e19a98de682092e643946f80c2`.
- [Real M1 CI #42376564561](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42376564561):
  SUCCESS, 1,704 passed, 15 skipped, 32 subtests; separate ledger runner 10 passed.
  Focused stdlib suites: 23 bridge + 21 runtime + 6 Operator = 50 tests.
  Python/YAML/whitespace checks and independent changed-source blob readback passed.
- [Operator Issue #334 official receipt](https://github.com/quest7070-dev/AI-Foundation/issues/334#issuecomment-6707522448),
  [run #42376885235](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42376885235):
  SUCCESS on exact runtime main, formal API HTTP 200 and valid projection.
  API-reported state FAILED; six FAILED notices; actionable/input-required counts 0;
  task/activity windows empty; five service reports, two ok and three unavailable.
  Seven provider and seven route rows counted without their identities.
  These are the Operator UI window, not a complete inventory or proof that all
  six historical failures are present host outages. No approval or retry occurred.
- [Storage Issue #335 official receipt](https://github.com/quest7070-dev/AI-Foundation/issues/335#issuecomment-6707525553),
  [run #42376886000](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42376886000):
  SUCCESS on exact runtime main. System/home/worker targets observed, reported
  total 228.27 GiB and available 21.83 GiB. Read-only flag true for the system
  target and false for owner-home/worker targets, without inferring a fault.
  All six fixed stdout/stderr metadata entries were observed. The llama-swap
  entries each reported 266,485,588 bytes; do not sum identical log endpoints
  as independent physical storage usage without proving distinct files.
- [Selftest Issue #336 official receipt](https://github.com/quest7070-dev/AI-Foundation/issues/336#issuecomment-6707528691),
  [run #42376886286](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42376886286):
  SUCCESS on exact runtime main; all three fixed stdlib suites PASS, exit 0.
- Official authenticated github-actions[bot] receipts and all three Actions run
  conclusions/HEADs were independently read after execution. Queueing or HTTP
  reachability alone was never treated as acceptance.

Desktop Commander calls, added dependency/auth/daemon/scheduler/state-ledger,
service restart, model/provider call, Native/old193 signal, log-content upload,
cleanup/deletion and host permission change: zero.

Remaining boundaries:
- Operator UI-window counts cannot identify a private target or authorize
  approve/cancel/reconcile. Use the existing owner/Guard-specific interface
  for target-bound investigation and approved recovery.
- Log size/timestamp is not error content or a growth rate from one sample.
  No automatic log truncation, rotation or retention change is introduced.
- Unavailable data remains explicit. No missing-file, outage or physical-disk
  identity claim is inferred from it.
