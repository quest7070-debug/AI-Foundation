# M1 development bridge — Desktop Commander-independent route

Status: **ACCEPTED for bounded GitHub→M1 diagnostics and fixed trusted-main CI verification (2026-11-07)**.

**Current ownership update (2026-11-12):** References below describing
Kandev as the canonical development executor are dated acceptance history,
not the present task owner. The present source of authority is
`SYSTEM_ROLE_BOUNDARIES.md`: GitHub identity/CI plus Foundation
Guard/Harness admissible work, with existing bounded local9B execution.
This bridge still does not grant arbitrary shell, approval or release access.
Implemented by PR #286, merged to main at `c223866c1102c6f692657f9b7cf0c748050096d2`.
Both real M1 Issue requests completed with independently read GitHub Actions bot
receipts. This does not grant shell access or general development execution.

## Route

ChatGPT -> authenticated GitHub Issue -> trusted default-branch GitHub Actions ->
existing self-hosted M1 runner -> bounded read-only observation ->
GitHub Issue receipt -> ChatGPT.

This is an asynchronous GitHub-operation bridge, not another MCP server, not a
new Kandev development scheduler, and not a replacement for Foundation Guard.
It requires no inbound internet port or Desktop Commander agent on M1.
If M1 is offline, execution stays queued; source editing and Draft PR operations
through GitHub can still continue but M1 results cannot be claimed.

## Operator tool selection precedence — user decision 2026-11-07

For **all future AI-Foundation development assistance from ChatGPT or other
external AI operators**, choose an available tool in this strict order:

1. **M1 development bridge FIRST.** Try its accepted, bounded operation when
   the requested task is supported. As of acceptance, supported operations
   are `snapshot`, `selftest`, `triage`, `klm-status`, `runtime-status`, `source-status`, `verify-main`, `operator-status`, and `storage-status`. Do not imply that this bridge can
   run arbitrary shell commands, edit files, dispatch tasks, or restart services.
2. **GitHub SECOND.** If the requested action is not supported by the bridge,
   or the bridge cannot be used, prefer GitHub connector/API, PRs, Issues and
   authorized GitHub Actions. Follow the existing Canon and Kandev ownership
   boundaries; the underlying GitHub transport used by the M1 bridge does
   not change this priority.
3. **Desktop Commander LAST.** Use only when neither the bridge nor the
   GitHub route can accomplish the necessary action with the required
   evidence, and only within the specific authorized scope. Do not use
   Desktop Commander merely for convenience, speed, or a redundant check.

At each fallback, state the concrete missing capability, error, or blocker.
Do not repeatedly invoke a known-unsupported bridge operation, represent
queued Actions as completed, broaden credentials/permissions, or bypass
Guard, Native approvals, free/local-only requirements or Kandev's canonical
development lifecycle. When neither route can safely complete the operation,
report the exact blocker rather than silently switching to a new authority.

This order is an **operator-tool preference**, not a transfer of policy
authority to GitHub or the bridge, and it does not prohibit the existing
Kandev Control MCP within its independently authorized development role.

## Request

Nine fixed request types are supported. Create a new GitHub Issue in
quest7070-dev/AI-Foundation, authored by quest7070-debug:

1. Title: Foundation M1 Bridge: snapshot
   Body: <!-- foundation-m1-bridge: {"version":1,"operation":"snapshot"} -->
2. Title: Foundation M1 Bridge: selftest
   Body: <!-- foundation-m1-bridge: {"version":1,"operation":"selftest"} -->
3. Title: Foundation M1 Bridge: triage
   Body: <!-- foundation-m1-bridge: {"version":1,"operation":"triage"} -->
4. Title: Foundation M1 Bridge: klm-status
   Body: <!-- foundation-m1-bridge: {"version":1,"operation":"klm-status"} -->
5. Title: Foundation M1 Bridge: runtime-status
   Body: <!-- foundation-m1-bridge: {"version":1,"operation":"runtime-status"} -->
6. Title: Foundation M1 Bridge: source-status
   Body: <!-- foundation-m1-bridge: {"version":1,"operation":"source-status"} -->
7. Title: Foundation M1 Bridge: verify-main
   Body: <!-- foundation-m1-bridge: {"version":1,"operation":"verify-main"} -->
8. Title: Foundation M1 Bridge: operator-status
   Body: <!-- foundation-m1-bridge: {"version":1,"operation":"operator-status"} -->
9. Title: Foundation M1 Bridge: storage-status
   Body: <!-- foundation-m1-bridge: {"version":1,"operation":"storage-status"} -->

No labels needed. Additional prose, arbitrary commands, filesystem paths,
model names, process IDs, shell arguments and duplicate fields are rejected.
The issue title and body must match the event and freshly fetched live Issue.

The snapshot records actual host architecture, Python version, checkout disk
free space and loopback-port reachability for Operator, remote gateway,
Ollama, llama-swap and Harness. A listening port alone is not E2E readiness.
The selftest invokes only the fixed test_m1_development_bridge.py,
test_m1_runtime_status_probe.py and test_m1_operator_status_probe.py stdlib suites,
with a fixed argv and bounded timeout. No model load or Native task is started.

`triage` is a single, fixed, read-only M1 health snapshot for reducing direct
Desktop Commander troubleshooting: one-minute system load, physical RAM,
`vm_stat` reclaimable-page estimate (not a guarantee of usable model memory),
swap used, exact `ollama` / `llama-swap` executable counts, and metadata-only
runner-context launchctl entries with prefix `dev.quest7070.ai-foundation.`.
It also performs static 127.0.0.1 HTTP GET checks on Operator /health,
Ollama /api/version and /api/ps, llama-swap /health, and Harness /health.
Returns HTTP status or explicit unreachability, plus loaded Ollama model count
and aggregate VRAM bytes. Never returns HTTP bodies, model names, process args,
raw logs or credentials; a 404 is *not* a service-down verdict. The runner's
launchctl domain may differ from the actual GUI service domain.
All commands use fixed argv, no shell, no user-provided path or command.
No service start/stop, inference or state mutation is performed.

The receipt is a structured, bounded GitHub comment, with a unique
foundation-m1-bridge-receipt:v1:<issue_number> marker. The bridge accepts replay markers only from the authenticated
GitHub Actions bot and checks for an existing receipt before observing a
request again. A forged marker from an ordinary Issue commenter is ignored. When it cannot prove a
complete comment window it denies instead of asserting an empty result.
Failures are explicitly recorded and do not count as success.

The Actions checkout is pinned to event-time trusted main SHA, not PR/Issue
content. Token scope is contents:read and issues:write. Workflows receive no
additional host access, do not run untrusted commands, do not install a daemon,
and do not mutate Foundation, Kandev, models, Guard or system services.

## Owners

Foundation retains Guard/policy/verification. Existing ToolHive remains the
replaceable MCP boundary. Kandev retains development task/worktree/session
lifecycle. This bridge only adds a narrow GitHub-requested host observation
path. Any later development action must call the authoritative Kandev/Guard
interface rather than implement its own execution engine.

## Acceptance

1. Independently read back the Draft PR branch, paths, HEAD and focused tests.
2. Review and deliberately merge to main. Do not auto-merge.
3. Create one fresh snapshot Issue and independently inspect Actions run and
   receipt. Confirm M1 macOS ARM64 and real port observations.
4. Create one selftest Issue and verify real M1 test receipt.
5. Rejection/replay/edited-Issue cases are proved with fixture tests, not with
   repeated live Issue events.
6. Only then expand to additional *fixed read-only* status profiles.
   Host commands, file writes, service restart, task dispatch and Native
   effects remain out of scope until an independently reviewed authorization
   and reconciliation contract is accepted.

## Independent real-M1 acceptance receipt — 2026-11-07

- Source regression: [Foundation CI #42351421547](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42351421547) succeeded on exact PR head `58a7d59158a8e4d5c75b3fa74b943d1f756b0f5b`: 1,643 passed, 15 skipped, 17 subtests passed; separate unittest runner reported 10 passed. Main push CI also succeeded.
- Snapshot: [Issue #288](https://github.com/quest7070-dev/AI-Foundation/issues/288), [M1 run #42351936236](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42351936236): actual macOS/arm64, Python 3.9, checkout free 36.29 GiB; ports Operator 8766, remote 8793, Ollama 11434 and llama-swap 9292 reachable, Harness 3081 not reachable. Job success and GitHub Actions bot receipt independently verified. Port reachability is not service-health acceptance.
- Fixed selftest: [Issue #289](https://github.com/quest7070-dev/AI-Foundation/issues/289), [M1 run #42351992906](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42351992906): exit 0, PASS. Bot receipt and successful job independently verified.
- Desktop Commander calls: **0**. No local model inference, native signal, service lifecycle change or paid provider action occurred in the bridge.

**Accepted scope:** remote status snapshot and fixed regression selftest, using GitHub Issues + Actions Runner with official GitHub receipt. Separately, the existing Kandev Control MCP was confirmed connected and enumerated Development tasks without Desktop Commander; that remains the canonical development execution route.

**Not accepted / out of scope:** arbitrary terminal, remote file writes, service restart, Kandev task submission via this bridge, Harness 9B E2E, Native Guard effects, and equivalence to Desktop Commander. Development source changes remain available through GitHub PRs, and Kandev owns development task/session/executor work. If the self-hosted M1 Runner is disconnected, the GitHub-backed host operation cannot execute until the Runner reconnects. No asynchronous guarantee is implied.

## Triage real-M1 acceptance — 2026-11-07

- Implementation: [PR #293](https://github.com/quest7070-dev/AI-Foundation/pull/293), main merge 44e2616f086125dcc06de11fc164dcced9d2a577.
- Exact PR head 9d9ce664f3ae42977f9a9ea2436725b6d216e439: [Foundation CI #42353356603](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42353356603) SUCCESS: 1,649 passed, 15 skipped, 17 subtests.
- Real M1 [Issue #294](https://github.com/quest7070-dev/AI-Foundation/issues/294), [run #42353594889](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42353594889) SUCCESS. Independently read authenticated github-actions[bot] Issue receipt with operation triage and status OBSERVED.
- Measurements: physical 16 GiB, approximate reclaimable 3.52 GiB, swap used 1.02 GiB, one-minute load 4.91. Ollama API 200, one loaded model and aggregated Ollama-reported size_vram 2.96 GiB (not evidence of 9B model identity). llama-swap health 200. Harness port 3081 unreachable. Operator /health HTTP 404 is NOT proof of an Operator outage. The local9b-autodev launchctl label existed with no PID in runner context, not proof of failure of a scheduled/on-demand process.
- Fixed input, read-only metadata-only result, no model inference, no host mutation and no Desktop Commander use.

**Accepted:** snapshot, selftest, triage. **Not accepted:** arbitrary shell, file extraction, raw log text, service restart, Native effects, inference benchmarks or full Desktop Commander parity. Diagnostic observations are not service-readiness or failure proof without domain-specific evidence.


## Runtime-status and expanded selftest acceptance — 2026-11-07

Accepted fixed operations: snapshot, selftest, triage, klm-status, runtime-status.
PRs #309/#312/#314 implement runtime diagnosis; final main source
`89a4523fc96ca0f94d63966a436cda3a35c6235e`. Real M1 CI #42371789730 succeeded
(1,683 passed, 15 skipped, 20 subtests). Independently read official bot receipts:
runtime [Issue #315](https://github.com/quest7070-dev/AI-Foundation/issues/315)
and [run #42372082289](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42372082289);
fixed selftest [Issue #316](https://github.com/quest7070-dev/AI-Foundation/issues/316)
and [run #42372083486](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42372083486), PASS/exit 0.
Runtime-status adds owner-installed worker result/intake/start summaries,
last success/failure timestamps, error counts, GUI/user/system launchd distinctions,
implemented Operator /v1/models status, and instantaneous existing lease observation.
Harness is an on-demand CLI in this accepted worker, not a mandatory 3081 HTTP service.
No raw logs, arbitrary host operations, service changes, model calls or Native effects.
Desktop Commander use: zero. Detailed observations, limits and next work:
[M1 runtime-status acceptance](M1_BRIDGE_RUNTIME_STATUS_20261107.md).

## Installed source and fixed main verification

`source-status` reuses the owner-installed worker binding and returns only fixed
component fingerprints/size/update time. `verify-main` reuses the existing
Foundation CI unit job on the exact event-time main SHA, followed by a separate
bounded bot receipt. It may write existing CI test/cache state; it cannot select
an arbitrary command, branch, service operation or model. Kandev task operations
continue through the existing Control MCP, not a duplicate bridge lifecycle API.
See [fixed verification and source inspection](M1_BRIDGE_DEVELOPMENT_VERIFICATION_20261107.md)
for ownership, token scopes, limits and live acceptance. Implementation is accepted on real M1: source-status Issue #330 and
verify-main Issue #331, both successful with independently read official receipts.


### Source inspection / verification live acceptance

PR #329 main `11b631bdd9a86d1b27857f5cf3f417e9ca6d117f`; real M1 source CI
#42374315217 SUCCESS. Fixed verify-main #331/run #42374566253 SUCCESS:
1,695 passed, 15 skipped, 24 subtests, official PASS receipt with exact SHA.
Source-status #330/run #42374565997 SUCCESS: 8 installed fingerprints obtained,
worker independently matched its recorded GitHub install source, one component
UNAVAILABLE. Existing Kandev Control MCP remains connected. Desktop Commander
calls: 0. Full evidence: [verification acceptance](M1_BRIDGE_DEVELOPMENT_VERIFICATION_20261107.md).

## Operator and installed-storage observations

`operator-status` reads only the existing formal /api/human API and returns
fixed state/function counters, bounded UI-window counts and timestamps. It
withholds task text/results, notice details, IDs and bindings. It cannot approve,
retry or reconcile an effect. `storage-status` reads fixed filesystem capacity
and owner-LaunchAgent log stat metadata, including the installed-worker volume;
no directory scan, log-content read, cleanup or write test occurs. Selftest now
runs the exact bridge/runtime/Operator stdlib suites. See
[Operator and storage status](M1_BRIDGE_OPERATOR_STORAGE_20261107.md) for source
contracts, privacy, coverage and real-M1 acceptance. No new service or runtime
state ledger is introduced; existing Guard/release ownership remains unchanged.


### Operator / storage live acceptance

PR #333 runtime main `c445bfd6c57202e19a98de682092e643946f80c2`.
Real M1 CI #42376564561 SUCCESS: 1,704 passed, 15 skipped, 32 subtests.
Official bot receipts and exact Actions HEADs independently accepted:
operator-status #334/run #42376885235, storage-status #335/run #42376886000,
and expanded selftest #336/run #42376886286 PASS/exit 0. Operator observation
exposed six FAILED notices despite HTTP 200; this is UI-window evidence, not
authority to retry or a complete host outage inventory. Runtime filesystem
availability was 21.83 GiB; fixed log metadata was obtained without reading logs.
Desktop Commander use: zero. See the linked Operator/storage acceptance record.
