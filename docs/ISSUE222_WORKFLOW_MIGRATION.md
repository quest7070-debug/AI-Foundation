# Issue #222 workflow migration checkpoint — 2026-11-06 JST

Pinned main: f7e1b9bc419fbdf40560f3f7fb7d1a9593c598df. These are source definitions, not installed runners. Classification is based on the saved workflow step inventory; unknown downstream effects remain unaccepted. No existing source inventory was rerun.

| Workflow/job | Classification and next action |
|---|---|
| ci.yml/unit | install/compile/tests + conditional host mutation; convert conditional phases together; pending |
| cua-driver-probe.yml/probe | read-only host observation; avoid unnecessary coarse lease; pending review |
| dev-autonomy-intake.yml/intake-tests | synthetic tests or real Ollama planning (job-specific); wrap planner preflight through report; pending |
| dev-autonomy-intake.yml/daily-intake | synthetic tests or real Ollama planning (job-specific); wrap planner preflight through report; pending |
| duckdb-mcp-probe.yml/probe | install/build + ToolHive mutation/probes; ownership review required |
| github-task-orchestrator.yml/discover-and-plan | read-only discovery/planning; classify local compute before migration |
| human-model-external-ledger.yml/synthetic-mount | synthetic temporary-filesystem test; converted source candidate; isolated CI blocked |
| human-model-ledger-init.yml/initialize | persistent SQLite creation; explicit authorization remains required |
| human-model-ledger-readback.yml/readback | read-only SQLite inspection; no model; pending review |
| human-model-m1-ollama-smoke.yml/local-ollama-smoke | model execution; whole-command wrapping plus #223 admission required |
| human-model-m1-volume-inventory.yml/inventory | read-only volume metadata; no model; pending review |
| human-model-ssd-provision.yml/provision | potential directory creation; explicit authorization remains required |
| jupyter-mcp-probe.yml/probe | install/build + ToolHive/workload mutation; ownership review required |
| librechat-v088-e2e-gate.yml/gate | browser E2E/process fixtures; isolation and process ownership required |
| m1-cognee-memory.yml/local-cognee | OSS install/model/graph writes; #223 and ownership review required |
| m1-document-standard-handoff.yml/synthetic-standard-parser | parser/FILES writes; whole-command/ownership review required |
| m1-human-model-activation-readiness.yml/inspect-existing-owner-view-runtime | read-only prerequisites; no activation; pending review |
| m1-human-model-publish-development.yml/publish-explicit-project-sources | publish/retrieval; persistent state and possible model; #223 required |
| m1-human-model-runtime.yml/daily-operator-runtime | deployed runtime verification; inspect downstream effects first |
| p02-multilang-inventory.yml/inventory | install/compile/inventory; whole-command conversion pending |
| playwright-mcp-probe.yml/probe | ToolHive/container/browser processes; ownership review required |

## One candidate conversion

The existing human-model-external-ledger synthetic workflow now runs source validation and the existing ten tests under one HostComputeLease plan. It uses the current interpreter, no extra dependencies, no shell interpolation, no model calls, and no physical SSD. Busy returns 75 immediately. Checkout/interpreter bootstrap and Actions post-cleanup remain outside the lease; this is a resource-phase contract, not proof of complete Runner.Worker lifetime. The runner must have the dedicated foundation-lease-disposable label; a label alone is not proof of isolation. Automatic cancellation of an older run is disabled. No installed runner configuration has been changed.

## Execution stop

BLOCKED_DISPOSABLE_RUNNER: GitHub connector rejected GET /actions/runners as an unsupported endpoint (INVALID_ARGUMENT). No independently verified dedicated runner identity, labels, UID, host membership or ownership was available. This is lack of access/evidence, not proof no disposable runner exists. No workflow was dispatched and no cancellation was issued. Commit uses [skip ci] to avoid launching ordinary CI on the shared runner. Existing CI successes apply only to the earlier tested source.

The issue's follow-up comment 6671502325 specifically requires stopping after source/static tests if the disposable runner is unavailable. Do not substitute two subprocesses for two independent GitHub jobs. Next: obtain read-only runner inventory and verify two disposable executors on the same M1/UID domain; run bounded independent holder/contender jobs, cancel only the task-owned fixture job, independently observe retained FD and recovery, then execute the migrated workflow and full M1 CI. No installed hook or background keeper is proposed.

## Issue #223 dependency

PR #236 remains at b9dacacd818652d14431bc61f0bfd3c43624e9c0, with its existing 18+19 offline tests retained, not rerun or rewritten. Trusted observation, real kernel lease ownership, model artifact identity, external Ollama consumers, swap/capacity and same-context replay remain NOT_RUN. HMAC alone proves none of those. Host-owned observation/nonce handling must be connected after the isolated runner/UID gate; effect_authorized remains false. No production admission follows from this candidate.


## Real disposable-runner result — 2026-11-06

The previous `BLOCKED_DISPOSABLE_RUNNER` account above is historical. Direct GitHub runner inventory now confirms **two** online, idle, same-M1/same-UID disposable listeners: runner #23 `p0-lease-20261106-a` and #24 `p0-lease-20261106-b`, each with **only** `foundation-lease-disposable` in their registered label list. Issue35 runner #22 is separate and was not used.

Because these two executors have no `self-hosted`/`macOS`/`ARM64` default labels registered, the Draft workflow's previous combined `runs-on` constraint could never match. On this Draft branch only, changed the matcher to `[foundation-lease-disposable]`, leaving the live default-branch workflow unchanged. Triggered **one** existing, model-free `workflow_dispatch` on exact source HEAD `a2691d452705752b742d78dcf0ce7e95ce13108f`. [Run #42215655211](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42215655211), job #127884886733, on actual runner `p0-lease-20261106-a`, **SUCCESS**.

The real job log confirms `WAITING → ADMITTED` (host UID 501, PID 92982) → source validation return 0 → existing 10 synthetic ledger tests PASS → `COMPLETE`. No model, paid provider, physical SSD or Native request; no runner binary/install setting or existing service was altered. One job finished in seconds. The two phases were under the same foreground HostComputeLease, but *Actions checkout remains outside the job lease*.

**Decision: disposable-runner presence and one real resource-phase job PASS; global host lease remains PARTIAL_BLOCKED.** This run does not prove two independent concurrent jobs, real Runner.Worker cancellation, inherited-FD survival after supervisor failure, runner-wide hooks, other callers' participation, or #223 RAM admission. Both dedicated runners have UID 501 but same-UID presence is not itself coverage. Do not claim full lifecycle, production permission or real 9B execution. For the next test, prioritize **one** bounded, purpose-built two-runner contention/cancellation acceptance, rather than re-running broad synthetic suites.

Machine-readable receipt: `docs/evidence/issue222/LIVE_DISPOSABLE_RUNNER_20261106.json`.


## Real cross-runner FD contention and recovery — 2026-11-06

A **single additional, model-free workflow_dispatch** under Draft PR #227 used the existing `human-model-external-ledger.yml` with the explicit `acceptance=two-runner` input and a new opt-in `scripts/issue222_disposable_pair.py`. The original ledger job was **skipped** for this input; no non-test model or storage workload ran. [Actions run #42217485767](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42217485767), source HEAD `6fbdd13d2273da4f505c2b8d5487c78dab892241`: **SUCCESS**.

- Independent job **lease-holder** ran on physical M1 runner `p0-lease-20261106-b` (host UID 501; job #127891023113).
- Independent job **lease-contender** ran at the same time on `p0-lease-20261106-a` (same M1 and UID; job #127891023488).
- The holder acquired a uniquely named **private fixture lock** via the existing `HostComputeLease` logic and explicitly passed its actual FD into a task-owned foreground child. The child verified the inherited descriptor using `HostComputeLease.hold()`.
- Child ready at **12:25:14.025 UTC**, holder closed its own FD at **12:25:14.202**, contender received the expected `HostComputeBusy` at **12:25:14.276** while only the child remained as holder. Child exited normally at **12:25:26.063**, holder marked done at **12:25:26.121**, and contender re-acquired the kernel lease at **12:25:26.136**.
- Both jobs completed successfully; no existing processes were signalled, no model/API/NATive effect occurred and the main workflow was unchanged.

**Accepted:** two *independent* GitHub runner jobs on the same real M1/UID domain, inherited-FD retention across a normal parent-context release, refusal of overlapping admission, and re-admission after the child exits. This is materially stronger than the earlier one-job synthetic process fixture.

**Still unaccepted:** actual GitHub Runner.Worker job cancellation/abrupt parent death, cross-UID coordination, external nonparticipating Kilo/Ollama clients, lease coverage for Actions checkout/post and the other source-inventory workflows, and Issue #223's conservative 9B RAM/residency gate. The test uses an **isolated private fixture lock**, *not* the canonical production lock. Consequently **#222 remains PARTIAL**, not global admission or permission to load 9B. Evidence: `docs/evidence/issue222/LIVE_TWO_RUNNER_FD_CONTENTION_20261106.json`. No broad test suite was re-run.
