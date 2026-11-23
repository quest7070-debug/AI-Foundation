# KLM queued-only fairness on installed 398592a3 — 2026-11-11

Issue: #562. This is a Draft source change, **not** a deployed KLM release. The active KLM service source is already pinned to `398592a317afc18dad7b1e55c3458324bb15889c` (Issue #587). This branch starts from that exact revision, preserving the #563 bounded LLMPerks reader and the #555 non-worker parent exclusion. Do not deploy the older main-based #623 source.

## Decision

The existing `DevObservation.idle()` requires no approved-pending development Issues. That is correct for strict idle but accidentally reserves all 9B compute forever when a ready Issue is queued yet never claims the shared lease. A queued Issue is demand, not active ownership.

Reuse **only** the existing 5-minute development worker, 15-minute KLM tick, `HostComputeLease`, and `work_steps` receipt. No new scheduler, background timer, process scanner, database or concurrent 9B backend.

* First known queued-only observation defers KLM as `WAIT_DEV_IDLE` and saves a queue fingerprint plus `dev_wait_since` on the already-PLANNED Work step.
* The **same** complete and fresh pending queue must remain inactive for at least **600 seconds** (two 5-minute development-worker opportunities). Then a single 240-second maximum KLM item may acquire the existing shared lease.
* A newly arrived/edited ready Issue changes the fingerprint and restarts the grace period. Active or uncertain development, incomplete/stale observations and missing fingerprints never bypass development priority.
* After lease acquisition, recheck both the development queue and real CPU/memory admission before the existing atomic work claim. If a development task arrives after the KLM claim, it waits for the same lease; KLM is bounded and is never preempted.
* No new entitlement or exception approval is inferred. On compute pressure, the work defers; no model eviction or paid fallback.

The fingerprint is a SHA256 of sorted ready Issue number/update timestamps, not Issue bodies. A missing or malformed timestamp/number never supplies a fairness fingerprint. A successful 600-second grace is retained across resource/lease-busy deferrals **only while the same complete queue is observed**; new demand or uncertainty resets it. The receipt contains a hash, timestamps and reason codes only. Previously stored `WAIT_DEV_IDLE` receipts without a fingerprint cannot authorize fairness until a new trusted observation.

## Acceptance

No-model focused tests run only the two KLM suites on this exact Draft branch; main retains its complete suite. Tests cover: unchanged queued-only queue after grace; new or edited Issue resetting grace; active/uncertain or missing observation never admitting KLM; compute pressure blocking despite grace. Standard exact-HEAD CI must pass, followed by separate pinned release review and an actual M1 readback proving: 9B is not doubled, a queued-only development item stops starving KLM, and a new ready Issue is given priority. This document does not authorize a main merge, live service switch, Native signal or replay of Issue #555.
