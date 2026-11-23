# Local9B false-contention pruning — 2026-11-10

## Evidence
- Canonical main `scripts/local9b_autodev_worker.py` used to reject **any**
  `Runner.Worker`, `llama-server`, `llama-cli` or generic `activation`.
  That rejects even idle CI processes and resident but inactive daemons.
- KLM already retired its analogous process-presence veto in
  `docs/KLM_COMPUTE_ADMISSION_PRUNING_20261108.md`; local9B worker did not.
- Actual owner M1 evidence in Issue #554: 16GiB RAM, ~5.50GiB reclaimable,
  6.28GiB swap, local9B not resident during one observed skill acceptance.
  These values are observations, not a new live capacity grant.

## Change
- **REMOVE** process-name enumeration and its blanket veto.
- **REUSE** KLM's bounded host CPU/RAM admission check only after acquiring the
  existing HostComputeLease. Unknown or pressurized resources defer.
- **RETAIN** shared Ollama /api/ps resident-model veto because *this particular*
  worker starts a second, isolated Ollama at 11436; running two 9B copies could
  exceed the M1's memory. Keep backend-port collision rejection.
- **RETAIN** no eviction/force-stop, single task claim, pinned model digest,
  Guard/Seatbelt, fixed test, Draft-only delivery, and no paid fallback.
- **FIX** unreachable shared-backend observation as a deferral, not a one-shot
  Issue failure. Admission reports only stable reason codes.

## Not solved by this change
- Waiting for shared Ollama residency: safe reuse would require an owner-managed,
  digest-pinned single-backend session arbiter with active-request tracking and
  independent real-M1 acceptance. Do not just delete the residency guard.
- KLM `WAIT_DEV_IDLE`: an approved pending Issue is queue demand, not active
  compute. Fair scheduling under the existing owner/lease, rather than another
  model or scheduler, needs separate source review of the development-priority
  policy. This patch does not weaken existing development priority.
- Cloud/free Harness delegation requires accepted account/billing/privacy gates;
  Draft #478 and #524 are not themselves live remote-model grants.

## Acceptance
- Run `python3 -m pytest -q tests/test_local9b_worker_admission.py tests/test_klm_compute_admission.py`.
- Review exact worker source and CI to verify no process-presence veto remains.
- Real M1 due-cycle / independent backend and task-claim readback remains required
  before production cutover. No main merge or M1 model operation in this Draft.
