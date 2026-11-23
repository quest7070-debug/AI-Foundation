# Durable Runtime

Hatchet is the current runtime candidate behind a narrow `DurableRuntime` boundary.
It owns scheduling, durable execution, worker distribution, retries and runtime observability.
It does **not** own Canon, privacy, approval, budget, effect authorization or completion verification; those remain in Guard.

```foundation-semantic
{"source":"src/ai_foundation/runtime.py","subject":"src/ai_foundation/runtime.py::CLASS::DurableRuntime@6:0","subject_kind":"SYMBOL","claim_kind":"durable_runtime_boundary","purpose":"provide a narrow replaceable durable-runtime boundary for scheduling, durable execution, worker distribution, retries and runtime observability","ownership":"the runtime backend owns scheduling and delivery mechanics; Guard retains Canon, privacy, approval, budget, effect authorization and completion verification","rationale":"keep durable scheduling replaceable and prevent runtime delivery semantics from becoming Foundation authority or exactly-once external-effect authority","failure_semantics":"runtime adoption remains incomplete when required recovery/reconnect/effect-reconciliation behavior is unverified, and runtime redelivery must not bypass Guard reconciliation","side_effects":"may schedule and redeliver durable work; external effects remain separately Guard-authorized and independently verified","change_impact":"changes must preserve runtime replaceability and the separation between at-least-once delivery mechanics and Guard-owned effect authority/verification","evidence":["tests/test_long_running.py","tests/test_hatchet_submission.py"]}
```

## 2026-09-17 M1 probe

Python SDK `hatchet-sdk 1.40.1` installed successfully in the project venv.
Official embedded mode was attempted on the M1. The sidecar downloaded and initialized its bundled Postgres files, but startup failed with `timed out waiting for database to become available`.
This is recorded as a real integration blocker, not a passing runtime test. Production containers were not changed.

Next runtime test should use an isolated Hatchet Lite/full local stack or diagnose the embedded Postgres startup without modifying existing production services. Runtime adoption is not complete until worker crash/restart, wait/resume, disconnect/reconnect and effect reconciliation pass end-to-end.

## 2026-09-18 embedded root-cause update

The earlier blocker is reproducible even from a clean bundled-Postgres shutdown. `hatchet-sdk 1.40.1` resolves embedded engine `v0.107.0`; its sidecar starts bundled PostgreSQL 18.3, but exits after about 30 seconds with `timed out waiting for database to become available`. The Python client's documented/default `ready_timeout_seconds=300` does not change this internal sidecar Postgres timeout.

A manually started copy of the exact bundled PostgreSQL binary reaches `database system is ready to accept connections`, so this is not evidence that Apple Silicon or PostgreSQL itself is unsupported. A failed/aborted embedded run can also leave PostgreSQL orphaned (PPID 1), causing the next attempt to fail with `postmaster.pid already exists`; therefore retries must first verify/clean the embedded Postgres lifecycle rather than blindly restart.

Decision: do not mark Embedded Mode as production-ready for this foundation. Keep the `DurableRuntime` boundary independent of Hatchet deployment mode. The next Hatchet validation should use an isolated Hatchet Lite/full local stack or an explicitly managed external Postgres, then run worker crash/restart, wait/resume, disconnect/reconnect, and effect-reconciliation tests. Existing production containers remain untouched.

## 2026-09-18 Hatchet Lite isolated E2E

An isolated Hatchet Lite stack now starts successfully on the M1 using `ghcr.io/hatchet-dev/hatchet/hatchet-lite:latest` plus a separately managed `postgres:16-alpine`. The stack uses its own Docker network and volumes, with host bindings limited to `127.0.0.1:18888` (HTTP) and `127.0.0.1:17070` (gRPC). Existing MultiLLM/LibreChat production containers were left running and unchanged.

The earlier Lite failures were test-environment configuration issues: a stale Postgres volume had credentials inconsistent with the attempted `DATABASE_URL`, and the Lite API requires the local self-host settings `SERVER_AUTH_COOKIE_DOMAIN`, `SERVER_URL`, gRPC broadcast/insecure settings, and related local flags. Recreating only the isolated test DB/volumes with a known dev credential produced an authenticated TCP `psql` success, all Hatchet migrations completed, and the Lite root endpoint returned HTTP 200.

A real Python `hatchet-sdk 1.40.1` worker then connected over gRPC, registered `ai-foundation-worker`, received `ai-foundation-e2e`, executed it, and the independent trigger process received `value='runtime-ok'`. This proves basic external Hatchet Lite server -> Python worker -> task result execution on the M1. It does **not** yet prove crash recovery, wait/resume, worker disconnect/reconnect, cancellation, or no-duplicate external effects; those remain mandatory adoption gates.

## 2026-09-18 worker crash/reconnect probe

A real Hatchet Lite task was dispatched to a Python worker, the worker process was killed with SIGKILL while the task was executing, and a replacement worker with the same workflow was started. Hatchet retained the same workflow run ID, detected the lost execution, redispatched it to the replacement worker, and the waiting client eventually received `ok=True`.

The task start marker was written twice, demonstrating the runtime's expected at-least-once execution after worker loss. The test side effect itself was guarded by an existence check and appeared once. This is important: Hatchet durability recovers work, but it does not by itself provide exactly-once external effects. Guard EffectIntent + idempotency + independent reconciliation remain mandatory for real side effects.

This probe passes worker kill/reconnect/recovery. It does not yet pass the stronger crash window where an external effect succeeds and the worker dies before recording completion; that must be tested through the real Guard effect boundary rather than a task-local marker.

## 2026-09-18 crash-after-effect Guard probe

The stronger Guard crash window was exercised separately at process level: Guard persisted `EXECUTING`, the fake external system committed the effect, then the Python process terminated immediately with `os._exit(91)` before Guard could persist `OBSERVED`. A new process loaded the SQLite Guard state and invoked the same run. It observed the real-world state, transitioned the existing intent to `VERIFIED`, charged the budget once, and did not call execute again (`COUNT` remained 1).

A permanent regression test now covers the equivalent persisted `EXECUTING` + successful independent readback state. This validates the core no-blind-retry rule across an actual process-death boundary. The next combined E2E should place this Guard path inside a Hatchet task so Hatchet redispatch and Guard reconciliation are exercised in one run.

## 2026-09-18 combined Hatchet + Guard retry probe

Hatchet Lite and the persisted Guard effect boundary were exercised in one real workflow run. The first task attempt persisted the effect intent, committed the fake external effect once, then simulated loss immediately after the effect. Guard returned `UNCERTAIN_RECONCILE_REQUIRED`; the task deliberately failed so Hatchet retried the same workflow run.

On Hatchet's retry, Guard loaded the persisted `UNCERTAIN` intent and performed independent readback instead of executing the effect again. The result was `VERIFIED_COMPLETE`, effect execution count remained exactly 1, final Guard status was `VERIFIED`, and paid cost was charged once (`7`). The waiting Hatchet client received the verified result from the same workflow run.

This passes the combined runtime-retry + Guard-reconciliation path. A literal OS-level worker death inside the combined task is still a separate harsher variant; the earlier worker SIGKILL probe and Guard process-death probe cover each boundary independently.

## Guard effect-claim crash recovery (2026-09-18)
A live M1 process acquired the SQLite effect claim, persisted `EXECUTING`, performed a fake external effect, and then blocked inside `execute()`. The process was force-terminated externally while the durable state was `EXECUTING`, `spent=0`, and the external execute count was 1. A fresh process loaded the same database and reconciled the observed `DONE` state to `VERIFIED`, charged 7 once, and left the execute count at 1. This validates claim + crash recovery without blind duplicate execution for the tested boundary. It does not imply exactly-once delivery.

## 2026-09-18 literal Hatchet + Guard SIGKILL E2E

The combined task now passes a literal OS-level worker death after the fake external effect. The worker was terminated with `kill -9` while Guard had persisted `EXECUTING`; Hatchet later redelivered the same run to a replacement worker. The runtime-side `GuardedRuntimeCall` treated `EFFECT_IN_PROGRESS` as a live lease/defer condition rather than an application failure, then retried Guard after the lease expired. Guard reconciled by independent readback and did not execute the effect again.

Final state was `VERIFIED`, execute count remained exactly 1, and paid budget was charged once (`7`). Hatchet recorded one application retry for its task-timeout recovery path on this version, so correctness does not depend on Hatchet classifying worker loss as an internal retry. The Guard/runtime boundary owns no-blind-retry safety.

A test-harness issue was also found: the remote commander's process-termination action did not terminate the underlying Python worker in earlier attempts. The passing probe used a direct OS `kill -9` and verified the PID disappeared before the replacement worker started. Earlier conclusions drawn specifically from those ineffective kill attempts are superseded by this probe.

## 2026-09-18 durable orchestration state boundary

Specialist orchestration now has its own SQLite-backed work-step state (SQLiteWorkStore / DurableWorkRunner). This state is deliberately separate from Hatchet: runtime redelivery may repeat scheduling/execution, while foundation work state decides which specialist steps are already VERIFIED and must not be repeated. Tests prove reopen after failure, durable WAITING_HUMAN, resume without repeating prior VERIFIED work, and Research -> Data -> Effect pause/resume without repeating Research.

This does not replace Hatchet or claim a new scheduler. Intended composition: Hatchet/runtime redelivery -> DurableWorkRunner -> specialist/capability -> Guard for effects. Next runtime E2E wraps this runner in a real Hatchet task and kills/redelivers around a multi-step job.

## 2026-09-18 DurableWorkRunner inside real Hatchet SIGKILL probe

A real Hatchet Lite workflow wrapped DurableWorkRunner with two persisted steps. Research completed once, the effect step committed an external marker, then the worker killed itself with literal SIGKILL. Hatchet redelivered the same workflow run to a replacement worker. DurableWorkRunner correctly skipped the VERIFIED Research step, but intentionally returned RUNNING for the orphaned effect step rather than blindly repeating it. External marker count remained one and Research count remained one. This proves runtime composition and exposes the next required gate precisely: RUNNING step reconciliation must delegate effect uncertainty to Guard/effect state and only then transition the work step to VERIFIED/FAILED/retryable. The workflow must not report successful completion merely because the work runner returned RUNNING.
