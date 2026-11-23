# KLM resource admission v4 — SHA-pinned GUI owner cutover

Date: 2026-11-08 JST. Canonical code: `quest7070-dev/AI-Foundation`.

## Exact review bounds

- Installed KLM-only source: `4e71e42ecc3aa14d740ed4e198c032669b68aba2` (APPLIED #394).
- Reviewed resource-admission source: `cd12f042b186898b2734427b6ccb0f621c76f410` (merged PR #401; real M1 CI 1,917 PASS / 15 SKIP).
- One existing GUI-owner LaunchAgent: `dev.quest7070.ai-foundation.klm-drive`, `StartInterval=900`.
- No new scheduler, model, paid provider, Native/Guard/Operator/HumanModel/owner-write action, external data import or cancellation of running development.
- Pin previous and new entry/9B handler blob SHA and all new KLM lifecycle modules including `klm_compute_admission.py` and `m1_klm_status_probe.py`.
- Reuse prior exact-owner GitHub live Issue validation, M1 UID, private config, current service contract, unmodified rollback plist/backup and post-bootstrap independent readback.
- Retarget future one-item retry Intent Issue and its exact workflow to the new pinned release. Keep the existing #396 staged intent in the same private Work DB; **do not restage or duplicate it**. Remove obsolete `SOURCE_READ`/`ONE_REQUEUE` GitHub Action stage allowlist values, since all real source reads now belong only to the GUI KLM host.
- Maintain **no `RUNNING` KLM Work of any type** (source intake, retries, old-atom review, polls or audits), development idle, shared HostComputeLease, GUI label idle and transaction-safe state. `PLANNED` means durable queue only and may survive code-only cutover; it is never silently mutated by this release.
- **Retired overconstraint in deployment only:** checking `llama-server` presence and resident Ollama model. Deployment only swaps pinned KLM source; it does **not** run 9B. Resident model is not proof of compute contention; model admission remains under the newly reviewed GUI host worker.
- Full keep/delete rationale and new gate codes: `docs/KLM_COMPUTE_ADMISSION_PRUNING_20261108.md`.

## Strict owner Issue

Title: `Foundation KLM resource release: cd12f042`

Body:

```
<!-- foundation-klm-resource-release: {"version":1,"release":"cd12f042b186898b2734427b6ccb0f621c76f410","previous_release":"4e71e42ecc3aa14d740ed4e198c032669b68aba2","scope":"klm-only","intent":"2026-11-08-owner-request"} -->
```

The fixed workflow `.github/workflows/m1-klm-resource-release-v4.yml`
must run **only after** real M1 CI of the new release entry is green and the
exact reviewed branch is merged to main. One terminal `APPLIED` (or idempotent
`ALREADY_INSTALLED`) bot receipt is necessary but not sufficient for full KLM
9B acceptance. Retire the one-shot workflow promptly after APPLIED.

## Independent follow-through

Request one read-only `klm-status` receipt *after* switching. The first
`NOT_DUE` report alone does not prove model execution. Wait for due
`CURRENT` cycles and verify source-bound retry intent, historical FAILED ->
PLANNED -> VERIFIED state, old atoms rebuilt and actual non-effect relation /
owner placement candidate receipts; preserve 0 unauthorized Inbox writes.
Keep the previous release and rollback backup until complete acceptance.

**Explicit Decision:** code-source cutover may proceed only under the above
bounded owner Issue; there is no permission to re-issue existing retry intent,
to bypass source revision/hash checks or to claim new semantic success from CI.

## Observed overconstraint and precise repair

- #405 attempted the first reviewed cutover; exact M1 receipt was `DENIED/KLM_WORK_ACTIVE`, no KLM service switch.
- Independent fixed bridge #406 then verified **1 PLANNED / 0 RUNNING** KLM intake Work, **2 FAILED / 3 VERIFIED** intake, **1 VERIFIED** source-bound retry intent and **1** preserved retry history. The previous `PLANNED OR RUNNING` gate conflated queued and running work.
- Follow-up correction: the release source uses owner-private SQLite `mode=ro` to count `status='RUNNING'` across **all** `klm-%` Work job identities and denies only genuine active KLM execution; the existing 900s service-idle gate, shared HostComputeLease and fresh development priority stay mandatory. `PLANNED` queued Work persists untouched in the same DB and will resume under the new GUI source after the next due cycle.
- The change is confined to the v4 one-shot release path; it does **not** auto retry or grant authority to historical Work, and does not skip the existing KLM worker's own source verification and Work claim.
- Re-run M1 CI with a synthetic queued-vs-running regression, merge only green, then use one new exact owner issue. #405's DENIED receipt cannot be overwritten or reused.
