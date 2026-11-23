# Issue 222 — job command lifetime admission

Decision after M1 CI and independent readback: **PARTIAL_BLOCKED** for globally coordinated M1
operation. This is a narrow opt-in source change on top of Draft #219, not a live
runner installation. No models are invoked by acceptance.

## Pinned sources and coverage

- Canon main: `f7e1b9bc419fbdf40560f3f7fb7d1a9593c598df`.
- Draft #219: `1d49b4525aceb02aa4127e4526a88a80920b9841` (implementation base).
- Research Draft #202: `c194e9f574043fedde66cfc82490c771ed32dec7` (not copied).
- Draft #8: `e3e6db1f5154cc14f1ae682d3b9b7ca4d8e10d22`.
- Separate integration/files: `be8df7415facd6de10434e8a60b39041d9c46894`.
- Separate integration/paseo-feedback: `f23a85b498e589b4f50608e62af915fb8e2e0a23`.

`evidence/issue222/workflow-inventory.json` enumerates **350 self-hosted job
definitions** across these six snapshots: 21 each in main/#219/#202/files,
133 each in #8/feedback. These are source definitions, not 350 installed runners.
The Markdown table is the path/job/labels/coverage index. Each JSON job includes
step names, command hashes, lease wrappers, possible effects, timeout and
concurrency declarations. No workflow from a Draft is treated as deployed.
Effect flags are conservative triage; e.g. a name containing runtime does not
prove an inference occurred. The pinned source is available for exact command
review. Missing runner ownership is explicitly UNKNOWN pending observation.

The current policy still has **no full-job participant deployed**. Three commands
on #219 cooperate (Foundation pytest, local planner, HumanModel Ollama smoke).
Every other listed job is uncoordinated; dependency installs, compile, setup,
conditional host probes and post-checkout actions are not covered by that
step wrapper. New source below supplies the foreground job contract but does
not silently label existing YAML jobs as participants.

## Existing inference paths, retained

| Call path | #219 participation | Remaining boundary |
|---|---|---|
| Operator/gateway → inference composition → dispatcher → llama-swap | HTTP exchange leased | Persistent residency after HTTP; source not deployed |
| Direct LlamaSwapExecution in phase_h_evidence, external_log_maintenance, lifecycle sweep | Uncoordinated unless caller injects lease | Optional constructor default is not global enforcement |
| LocalExecutionDispatcher → configured OpenAI-compatible endpoint | Unknown host / not M1 leased | Remote local endpoint ownership and vision calls |
| dev_autonomy_intake → shared Ollama /api/chat | Workflow command wrapper only | Direct invocation / third-party clients |
| human_model_ollama_smoke → ollama_proposal_runner | Workflow command wrapper only | Experimental/direct invocations |
| HumanModel runtime / Cognee → Foundation gateway | Composition boundary when selected | Caller lifecycle, endpoint configuration |
| Pi/Paseo/Familiar and research 2B/4B/9B in separate sources | Not globally accepted | Native/experimental routes are not executed here |
| External shared Ollama users | **Outside coverage** | Advisory flock cannot control them |

`local-call-sites.json` records exact source references rather than asserting
complete dynamic reachability. Active service settings, all independent clients,
and differently owned runners cannot be inferred from repository files.

## Implementation and lifecycle

Reuse `HostComputeLease` and the existing CLI. New opt-in command:

```sh
python3 scripts/host_compute_lease.py job --max-wait-seconds 120 --plan /absolute/job.json
```

The trusted plan has version 1 and an ordered `phases` array of `{name, argv}`.
Arguments are executed directly, without implicit shell interpretation. A caller
may explicitly choose a reviewed shell script. All install/compile/test/post
commands must be foreground phases in this **one invocation**. Acquire occurs
before the first phase and lasts across phase transitions and final reaping.
The existing llama-swap owner, aliases, routing and Guard decisions are unchanged.

The supervisor retains the same lock FD and passes it explicitly to each child.
Nested Foundation calls validate its inode, device, owner, private mode and link
count against the canonical path. They neither unlock nor close the borrowed FD.
Validation exceptions no longer surround the consumer's `yield`: an OSError in
inference cannot accidentally cause a second context entry. Stale/forged FD,
hardlink, symlink and path replacement are rejected. An explicitly different lock
domain ignores an unrelated inherited descriptor (used only for isolated tests).

Release is by **closing**, never LOCK_UN. This matters if a supervisor exits while
a delegated child still computes: the child keeps the lease until it exits.
There is no detached guardian, TTL expiry, PID reuse-based release, lockfile
deletion, forced takeover, process enumeration followed by killing, or model stop.
After crash/restart the kernel closes dead process FDs. A surviving worker keeps
the lease, so a new job waits/defers instead of overlapping it.

SIGINT/SIGTERM marks cancellation, stops subsequent phase admission, and reaps the
current foreground child **without signalling it**. Normal failure preserves the
child exit code. A hard supervisor termination leaves the inherited FD with the
child. There is no guarantee of immediate cancellation of an unbounded child;
the runner's own cancellation/timeout semantics must be independently validated.
Detached descendants or runtimes closing delegated FDs are **unsupported** and
must not be admitted using this contract.

Contention emits WAITING then DEFERRED and returns 75 after a bounded wait (0–600
seconds); invalid state returns 76. No auto-resubmission or label-triggered queue
exists. The workflow must keep those outcomes non-success. No model cooldown or
cloud/paid fallback is added. Existing LOCAL_RESOURCE_DEFERRED remains intact.

## Why this is not yet a runner-wide solution

GitHub concurrency coordinates matching groups within its service, not local
Ollama callers; distinct groups/workflows still overlap. Per-step processes
cannot retain a plain FD across separately spawned later Actions steps. A start
hook that exits drops its FD; a background hook keeper risks releasing early or
surviving a cancelled job. No such keeper is installed here.

This plan runner can cover a foreground job command, but cannot wrap an already
running Runner.Worker from inside a normal Actions step. Real adoption requires
either a reviewed whole-command workflow conversion or a supported runner-owned
entrypoint that preserves the FD across Worker/step execution. Neither is enabled
by this PR. Do not replace runner binaries or set hooks opportunistically.

The canonical lock is per **real login UID**, independent of HOME overrides.
Different UID means a different coordination domain, not mutual exclusion.
Same-UID code holding an inherited FD is a capability holder; arbitrary forks that
retain it are delegates, not independent jobs. The independent-fork test drops
the capability before admission. This is cooperative resource control, not a
security boundary against malicious same-UID code that unlinks lockfiles or
closes FDs. A shared multi-UID policy needs separately authorized host ownership.

## Acceptance and next gate

Run `python3 -B -m unittest discover -s tests -p test_host_compute_job.py -v`.
Tests use temporary lock domains and bounded synthetic children, not model APIs.
Synthetic cancellation uses only the fixture's own parent; no existing user PID
is signalled. Full Foundation CI also exercises existing lease/routing tests.
The dedicated CI step prints the synthetic results and read-only runner UID,
labels/environment and current Runner.Listener/Worker identities. Environment
hook presence is observation, not proof of hook coverage.

Tests cover independent jobs, every phase transition, nested calls, failed phase,
cancellation, abrupt exit, self-timeout, surviving delegated child, FD substitution,
path replacement, hardlink/symlink, distinct UID rejection, unrelated fork and
explicit nonparticipant behavior. Live runner restart/cancellation, cross-UID
coordination, external callers and real models are **NOT_RUN**.

Issue #223 may proceed only as read-only/proposal-only work while this deployment
gate is blocked. No `ADMIT` for 9B or global host safety follows from a green CI.
Before production acceptance: choose one reviewed runner entrypoint/workflow
conversion, prove FD retention and timeout/cancel behavior on a disposable runner,
reconcile every inventory row with its owner, then independently accept #223's
resident-model/capacity gate. No current runner or service is changed here.

## Verified M1 result — 2026-11-06 JST

Foundation CI [42121856706](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42121856706), job 127575992923: SUCCESS. Source HEAD `582511f46091f39d68a00fbb7a5f7e59a8af3825`; Actions checkout `b4ec40c8d62944de46b00d246ce9aa04c6d3e1bf` has the identical tree `e56cbd8323aa603794d767dba46cee6af63c8537`. Full suite: **1650 passed / 15 skipped**, plus the dedicated **16/16** process acceptance. The latter repeats the focused contracts for explicit step evidence, not additional model coverage.

Read-only observation: macOS ARM64, m1-runner, login yourname / UID 501; two Runner.Listener processes and the current Worker shared UID 501. No job-started/completed hook variables were configured in this process environment. This is a bounded observation, not proof that no other runner configuration exists. Both live services and runner configuration remained unchanged.

Implementation readback matched all 11 files. The subsequent evidence-only commit does not change tested code. See `evidence/issue222/checkpoint.json`, `m1-ci-excerpt.log`, `runner-observation.json` and `overlap-comparison.json`. Acceptance remains **PARTIAL_BLOCKED** for global coordination, while the opt-in foreground job contract and inherited-FD fixes are ready for source review. Issue #222 is not closed; #223 is restricted to proposal-only/read-only work.

## Final M1 follow-up — 2026-11-06 JST

The fork fixture now runs in a fresh single-threaded subprocess, avoiding fork from the multi-threaded pytest process. The focused offline test passed; final [M1 CI 42122508236](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42122508236) passed **1650 tests / 15 skipped**, plus dedicated **16/16** process tests. Only the existing pydantic event-loop warning remains.

Tested HEAD db513e26226134e52133db33f5e37538d072fb55 and checkout merge 28d4c3fe1cd0f61770961ab5b798a10670ad0a48 share tree 373473fbd3a0adb98afa3aa48b42ae9b11e631db. The final evidence commit changes documentation/logs only. Previous CI evidence is preserved; the checkpoint links both runs and records source/evidence hashes. See m1-ci-followup.log, runner-observation-followup.json, and fork-isolation-test.log.

Global acceptance remains **PARTIAL_BLOCKED**. Next work is a reviewed whole-job workflow conversion or runner entrypoint, followed by actual cancellation/FD-retention acceptance on a disposable runner. This PR does not deploy it. Issue #223 can advance only as read-only/proposal work.
