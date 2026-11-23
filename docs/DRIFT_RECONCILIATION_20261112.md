# Canon drift, forward deltas and autonomous development reconnection — 2026-11-12

Reviewed source baseline: `fc9109e9436ca83fbdb96c3337a4b59cbab63b74`. **Source only**, not an installed M1 deployment. Preserve historic heads and original owner approval/Guard/one-shot states. No additional scheduler, billing route, 4B fallback, process stop or Native signal.

## Canon owner corrected

`SYSTEM_ROLE_BOUNDARIES.md` no longer assigns every development task to Kandev. GitHub owns source identity and CI; Foundation Guard/Harness owns the finite task permissions, roles, inference selection and independent verification. DSH→OpenCode and Codex OSS are optional frontends; existing local9B worker remains the live-ready-Issue executor. Ordinary GitHub intake previously returned `WAITING_FOR_PASEO_NATIVE_WORKER_GATE` for all work; the source now truthfully reports `READY_ISSUE_WORKER_SEPARATE`. This is a status/ownership correction, not a new runtime grant.

## Forward feature recovered from closed #607

Main had `human_model_management_audit.audit_ledger` but its M1 ledger readback lacked the call, and KLM had no projection of owner structural health. This branch wires `human_model_ledger_verify.verify()` to existing bounded aggregate audit, and adds fail-closed status/exit for corrupt source hash/Views. KLM `owner_management_readonly_audit` reuses that readback once per existing due tick. Missing USB source is UNKNOWN and never blocks independent Drive work. Existing literal source results now flag disputed/inference evidence as review-required, never a verified personal fact. Two synthetic tests and the full dated HumanModel lifecycle specification are restored from original #607 HEAD `518d11447304b4df00686e8c0f6504562f46f6a6`; no auto private ingestion.

## File-level compare of eight priority old PRs against baseline main

| Old PR | Blob identical | Tracked files changed | Absent old paths | Decision |
| --- | ---: | ---: | ---: | --- |
| #607 | 13 | 9 | 3 | Recovered missing ledger↔KLM source readback, contract and tests; remaining changing paths need semantic review |
| #481 | 43 | 4 | 14 | Foundation admission/Drive/Guard adapters already main, 11 one-off host workflows remain intentionally unactivated |
| #478 | 25 | 34 | 11 | Provider/Harness code mostly current; retired Jules and old Groq adoption not enabled absent owner no-charge evidence |
| #470 | 1 | 6 | 23 | Obsolete P4 direct cutover replaced by newer owner-scoped releases; no service switch |
| #256 | 4 | 3 | 3 | Compact-edit available in main; experiments not automatically made runtime |
| #248 | 7 | 10 | 0 | Existing worker, repair and Draft paths evolved; behavioral equivalence needs separate proof |
| #242 | 0 | 3 | 73 | Old DSH/9B isolated experiments, not deployable as a complete runtime |
| #236 | 3 | 1 | 6 | Offline evidence v2 verifier already included; old capacity contracts historical |

Counts are **file-level**, not evidence of complete semantic recovery. The other 44 closed PRs' exact immutable source heads remain available in `PR_CONSOLIDATION_20261112.md`. Closing/merging #741 did not make their entire code operational. Do not copy historical Native/credential/model-install bits to satisfy a file count.

## Existing bounded autonomous execution path and what remains

The installed worker source already performs `collect_failure_candidates` → `collect_ready` → single task claim → Guard/tests/repair/Draft. Existing `standing_delegation` can create a new ready Issue only for 3 exact, host-preapproved main test/source pairs after a genuine reproduced fixed-test failure; `m1_owner_candidate_admission` separately composes measured free/benefit/M1 fit, Drive and Guard. General CI-generated diagnostic Issues still do not have auto-ready permission. Correcting the intake's false Paseo gate *reconnects the documented current handoff*, but this source patch **does not establish a fresh full unattended E2E**. Live M1 one-task execution and Draft/CI readback remain open, as does exact-main CI if shared compute is busy.

After #741, main push CI exited `HOST_COMPUTE_BUSY` before pytest (code 75). This is resource deferral, not an observed test assertion. Do not mask that failure as SUCCESS or weaken protection of the active M1 9B; test in the next naturally free lease window.
