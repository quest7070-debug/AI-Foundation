# KLM priority gate: executable local9B work versus exact Native-only approval

This Draft is stacked on **PR #296** (parent HEAD `fc354a1c470630537c3b8a9a170b484f8249809d`), without editing Work's OAuth, Drive/Sheets transport, Changes pager, 9B handler, host scheduler or original HumanModel/Native receipts.

## Actual evidence that motivated the correction

At 2026-11-07 17:56 JST, the real macOS KLM host report under the private M1 runtime had:

- Native OAuth **`AUTH_BOUND_READ_PROBE_PASSED_TICK_REQUESTED`** saved at 17:46 JST.
- A subsequent authenticated poll saved at 17:47 JST: **`RESYNC_PARTIAL`**, 20 pages, 6 new Inbox pointers, `drive_auth=BOUND`.
- Registered LaunchAgent `dev.quest7070.ai-foundation.klm-drive`: `runs=5`, `last exit code=0`, `run interval=900 seconds`.
- GitHub-backed `DevObservation(approved_pending=1,active_or_uncertain=0,complete=True)` prevented inferencing. The one unconsumed ready issue is [Issue #35](https://github.com/quest7070-dev/AI-Foundation/issues/35).

The exact GitHub body of #35 is a reviewed **Native-only** `foundation-autodev` marker with `native_handoff`, a single `src/ai_foundation/paseo_foundation_runtime.py` target and an independent `tests/test_paseo_signed_ingress_slot.py` acceptance path. It has **no** `foundation-autodev-task` fenced finite-task recipe. The current local9B worker's `issue_task` rejects it as `SCOPED_TASK_CONTRACT_REQUIRED`. The preexisting KLM observer counted all ready-but-unsupported Issues as pending executable development, even though the worker cannot run them. Therefore a Native-only canary can permanently starve otherwise idle low-priority KLM 9B processing.

## Change

The development priority observer now separates **one exact, narrowly validated Native-only canary shape** from runnable local9B tasks. The Native marker must be owner-scoped, duplicate-key-free, contain exactly one known target and exact signed-ingress acceptance test, have no finite-task block, and carry no dependencies. Everything else that fails local9B recipe validation, including missing and malformed markers, **continues to count as conservatively pending**.

A new `DevObservation.native_only_approved` diagnostic field reports this class without granting any new work/effect authority. A genuinely executable approved local9B task still blocks. Any active/uncertain started or claimed local9B work, occupied CPU/Metal/model endpoints and the existing shared HostComputeLease still block KLM. The Native Issue's original ready label, Guard decision, source, service or exact approval is **not changed**.

This change only corrects the *read-only interpretation* of whether a queued Issue is an executable demand on the **local9B worker**. It does not approve running KLM when the host is actually busy, is missing a model lease, or fails the authenticated Drive sync gate.

## Tests / acceptance

`tests/test_klm_native_only_priority.py` tests the actual #35-style Native marker, priority over an executable task, fail-closed malformed/mixed/duplicate markers, unknown GitHub API coverage and an unfinished local9B worker marker. All are synthetic no-model tests. The parent branch's Drive/Native code is unchanged.

**Actual M1 code CI:** pending. Source-only review is not a deployed host release. After CI, Work should incorporate the explicit observation into its latest host release only after independently checking that the next native Changes tick reaches CURRENT and the shared lease is actually free. Do not skip incomplete Drive synchronization or automatically rerun #35.

No main merge, external Drive source write, Native signal, paid provider or new model.
