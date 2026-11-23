# GitHub Issue intake for the local9B worker

The existing main `scripts/dev_autonomy_intake.py` can collect CI failures and publish diagnostic Issue candidates with `--publish-ci-task-drafts`. Such drafts are intentionally not approved. This remains separate from any inference planner; the local worker does not invoke 4B.

The persistent local worker now polls open Issues labeled `foundation-autodev:ready` every five minutes using authenticated gh, independently of the optional 4B planning path. Each executable Issue must contain exactly one block:

```foundation-autodev-task
{"recipe":"bounded-http-positive-limit","base":"main","field":"request_queue_size"}
```

The alternative supported field is `max_concurrent_requests`. Base may be `main` or an existing `local9b/` branch. The repository, file target, instructions and fixed sandboxed acceptance recipe are host-bound. Arbitrary file/test commands in Issue prose are not execution input. Unsupported/missing recipes are recorded in local intake.json as NEEDS_SCOPED_CONTRACT.

Ready label + exact contract is reread immediately before execution. Task identity binds Issue number, full body and update timestamp; changed approvals/content are refused. Start/result receipts prevent replay of consumed work. Previously completed legacy task is retained and not rerun. No merges, deploys, paid inference, new models or 4B calls.

Limit: this is live approved-Issue intake for one accepted recipe family, not automatic root-cause analysis or general arbitrary-code repair. Existing CI candidate publication is available but its scheduled deployment is not established by this change. Expanding file/test recipe families and automatic candidate-to-contract synthesis remains future integration.


## At-most-once consumption after a worker start (2026-11-07)

An approved Issue is a one-time task, not permission to restart indefinitely.
The worker already creates an exclusive `.started` marker before executing
any possible model action and keeps it after success, failure, timeout or crash.
A `HostComputeBusy` raised before execution completes removes this marker,
allowing a later no-effect retry.

Before queuing any refreshed Issue version, `collect_ready` now checks the
exclusive `results/issue-N.claimed` marker and all prior
`results/issue-N-*.started` and `results/issue-N-*.json` receipts.
The worker atomically creates `issue-N.claimed` before its task-specific
start marker, preventing two independent workers from starting different
revisions of the same Issue. Only the owning worker can release both markers
for a pre-model `HostComputeBusy`. Crashes retain the claim.
If one exists, the issue is reported `ALREADY_ATTEMPTED` and not queued
again, even if a comment, body or timestamp changes its task hash.
This covers successful Draft PRs and uncertain model-timeout/crash states;
a prior attempt cannot be silently replayed under a new hash.
Untrusted symlink receipts are refused for review.

If the user wants another attempt or new scope, they must open a new Issue
with the exact pinned recipe and separately apply the ready label.
The original Issue stays open for reviewing its Draft output; it is not
automatically closed or merged. The at-most-once change was subsequently
deployed to the installed M1 worker and its exact source/tests verified
(see `docs/evidence/development_loop/ISSUECLAIM_M1_ROLLOUT_20261107.json`).

## Selection and continuous progression (new source proposal)

See `docs/LOCAL9B_TASK_SELECTION_POLICY.md` for the explicit v1
source/evidence/admission/ordering policy. The candidate generator never
auto-grants ready authority. The worker picks **one eligible unconsumed Issue
per launch**, according to deterministic priority/evidence/FIFO ordering.
A pre-model busy defers without consuming the Issue; successful and uncertain
post-model runs remain consumed. These selection changes are on a separate
Draft branch until tested and installed.

## Bounded compact-first implementation (2026-11-12 source branch)

For an **already approved** `python-fixed-test` task whose host-selected
tracked Python source is a regular non-symlink file of 1–32,768 bytes, the
existing installed worker source now opts into the existing
`run_local_development_task(compact_single_edit=True)` mode.

- The first proposal asks the **same local 9B Harness** for a single exact,
  uniquely matching `search`/`replace` JSON pair. The trusted host rebuilds
  a complete Python file in memory and compiles it **before Guard write**.
  This reduces generated output tokens; it is **not** a second model, job
  loop, permission system or a speed guarantee.
- If the fast proposal is invalid or the fixed acceptance tests fail, only
  the **existing single full-file repair attempt** runs. Infrastructure and
  transport failures are not silently retried. The existing Guard, readback,
  fixed tests, optional independent review, lease and Draft PR checks remain
  authoritative.
- Oversized/unavailable/symlink sources and the legacy bounded-HTTP recipe
  use the original full-source path. No model or Issue text selects mode,
  targets, tests, providers, or budgets.
- This source change is not a live M1 worker release. Confirm exact-head
  Foundation CI and an independently read-back fixed-fixture M1 work result
  before treating the acceleration as deployed. Do **not** consume/replay an
  existing approved Issue solely to measure a speed improvement.
