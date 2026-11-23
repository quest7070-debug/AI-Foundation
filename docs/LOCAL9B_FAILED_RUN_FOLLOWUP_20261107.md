# Local 9B: failed fixed-test attempt -> review-only follow-up

## Verified real-M1 motivation

As of 2026-11-07 15:31 JST, owned LaunchAgent
\`dev.quest7070.ai-foundation.local9b-autodev\` had completed 102 ticks
and reported exit 0 while idle.

- Issue #270: result \`DRAFT_PR_PRESENTED\` with exactly one local
  \`qwen3.5:9b\` attempt and Draft PR #275.
- Issue #271: terminal result \`REPAIR_BUDGET_EXHAUSTED\`,
  two local 9B attempts, **no Draft PR**, no deployment.
- Issue #271's consumed \`.started\` and Issue-wide \`.claimed\` markers were
  still present; the live Issue intake reported \`ALREADY_ATTEMPTED\`.
  A new attempt cannot lawfully reuse the same ready label or edit.

No inference/workload was initiated by this investigation. Do not infer
the root cause from the public status alone: a specific failing source diff
or test diagnostic has not been independently published and approved.

## Scope

This branch is a child of #268 and changes ONLY the local9B failure capture
and diagnostic-candidate builder, not model settings, host leases, Native,
runtime source modules, DevelopmentLoop repair budget, or the KLM/Drive/HumanModel.

### Selection is evidence-based, not a heuristic

A diagnostic follow-up is eligible only if:

1. A consumed terminal real local 9B result has one of the fixed
   \`REPAIR_BUDGET_EXHAUSTED\`, \`NO_PROGRESS\`, or \`INVALID_PROPOSAL\` statuses.
2. Result task identity \`issue-N-HHHHHHHHHHHHHHHH\` exactly matches the
   original approved queue \`inbox\` receipt, and Issue-level claim and
   task \`.started\` marker persist. Reject missing, symlinked, mismatched
   or oversized receipts.
3. Original one-source \`python-fixed-test\` recipe validates with a pinned
   base SHA and exact test SHA256. Do not mine log prose, model reply, or
   generated source for the next target or command.
4. Original result confirms local \`qwen3.5:9b\`, unattended execution,
   no production activation, no delivery, and bounded attempts.
5. Store only original source/test pins, minimal status, attempts and
   a *hash* of failing feedback; no raw model/terminal failure text in
   the diagnostic event.
6. Existing \`publish_candidate\` clones the canonical source branch,
   verifies the pinned base and test, reruns the independent failing fixed
   test inside the existing Seatbelt boundary, and deduplicates by exact
   contract. Only then create a **new UNAPPROVED** GitHub diagnostic Issue,
   without a ready label. A reviewer must independently approve a distinct
   new bounded contract and Issue before any execution.
7. The original failed Issue is **never automatically retried**; its
   consumed marker remains and is not removed.

Excluded: any \`STOPPED\` or infrastructure failure, unknown/partial
write, unreadable effect, unfinished draft publication or delivered Draft.
Those require reconciliation, not repair retry. Unsupported legacy tasks
cannot be silently rewritten as generic tests.

### Runtime / idempotence

\`collect_failure_candidates\` first calls
\`capture_failed_run_candidates\` with a bounded scan of 1,024 completed
result receipts and at most 8 newly materialized candidate event files
per tick. Event paths are exclusive, fixed by original Issue/task identity,
0600 permissions; conflicting rewrites reject. Existing candidate
publisher uses the original, independent test verification and GitHub
body marker deduplication, not new job authority.

Capture is deterministic and model-free. If candidate publication is
unavailable, it is advisory and the separately approved issue-execution
path remains functional. No automatic ready labels, retries or full
new CI scans; normal 9B worker still runs on existing 300-second schedule.

## Acceptance

Source-only unit checks must cover captured #271-like terminal receipt,
idempotence, non-replay, no-content leakage, unapproved issue publication,
symlink/claim spoofing, unverified result and unknown-effect refusal.
GitHub CI must pass on the Draft PR's exact source HEAD.
Real M1 deployment, unattended candidate creation and independent GitHub
Issue readback are **separate acceptance gates**; do not assert production
activation from source-only CI.

No change to PR #279, Work's Drive adapter, HumanModel PRs or main.

## Standing main scan: pre-effect claim recovery (2026-11-13 source change)

The existing `scan_standing_main_regressions` protects each main SHA with a
durable exclusive claim so an uncertain GitHub Issue creation is **never**
silently replayed. Previously, the first failed fixed-test probe could set
`PUBLISH_MAY_HAVE_STARTED` even when it returned
`NO_CONFIRMED_TEST_FAILURE`, and a later `TASK_BASE_MOVED` before any
Issue creation would leave a forever-blocking claim.

A bounded fix now distinguishes **confirmed zero-issue work** from an actual
`AUTO_READY` Issue in the same scan. Only the source-only
`NO_CONFIRMED_TEST_FAILURE` and `TASK_BASE_MOVED` conditions may release
the claim when **no Issue has been published**. Ambiguous GitHub errors,
malformed acknowledgements, and all failures after an Issue was created still
retain the claim for reconciliation. No model, scheduler, CI-trigger or new
approval mechanism is introduced. This is a draft source fix until CI and
owner M1 readback acceptance.
