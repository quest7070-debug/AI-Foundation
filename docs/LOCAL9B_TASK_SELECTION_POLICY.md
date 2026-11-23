# Local 9B development task discovery and selection policy (v1)

**Execution:** dedicated M1 local-only 9B worker. **Canonical authority:** GitHub Issues / source commits / independent tests / Draft PRs. **Not** an alternative Native/Paseo scheduler or an unrestricted repository coding agent.

## The object being selected

A task is not a string found in a log or an LLM suggestion. A runnable task is an **open GitHub Issue in this repository** that simultaneously has:

1. Explicit `foundation-autodev:ready` label and **no** `foundation-autodev:hold` label. The host may attach this same label automatically at Issue creation only under the exact, finite standing delegation below.
2. Exactly one schema-validated `foundation-autodev-task` JSON contract. Recipe comes from a finite host-owned registry; source, test, base and immutable pins are fixed in the contract; the model cannot substitute shell commands or test files.
3. No earlier `issue-N.claimed`, `issue-N-*.started`, or `issue-N-*.json` execution receipt, even if Issue content, labels or updated timestamp change.
4. A second, fresh Issue/contract read immediately before running. Hold, approval revocation, and content changes fail closed.
5. A **failing baseline** verified by the fixed host acceptance runner *before* model inference. The runtime verifies Git head and test bytes again. Already-passing tests do not generate needless code edits.
6. A free local qwen3.5:9b backend with the existing exclusive host lease and idle shared services. Occupied CI / models cause a pre-model defer, never eviction or unbounded retries.

A candidate generated from an arbitrary CI failure is **not** automatically ready. Logs, issue text and model opinions are observational evidence only. No authority flows from a failure count, severity guess, PR author or raw textual instruction.

### Standing delegation: three exact canonical-main regression pairs

The existing host publisher may attach the existing `foundation-autodev:ready`
label at creation **only** after a real independent failing pinned test on
current protected `main`, with a host-generated exact repair instruction:

| Writable source | Fixed independent test |
| --- | --- |
| `src/ai_foundation/notification_boundary.py` | `tests/test_notification_boundary.py` |
| `src/ai_foundation/task_result.py` | `tests/test_task_result.py` |
| `src/ai_foundation/question_bridge.py` | `tests/test_question_bridge.py` |

This finite standing contract is `DELEGATED_MAIN_PAIRS` in the already
host-owned `scripts/local9b_failure_candidates.py`, not a second permission
DB. Source, test, base SHA and exact instruction remain pinned in the existing
`python-fixed-test` recipe. The existing one-shot claim, current Issue/hold
revalidation, no-model red baseline, local free qwen3.5:9b and Draft-only
delivery are mandatory and unchanged.

**Never auto-ready:** non-main branches, any other file/test, modified
instructions, raw model proposals, failed/consumed 9B origin follow-ups,
already-existing candidate Issues, Native, Guard/authentication, personal
sources, credential handling, production deployments, unknown effects or
test-infrastructure errors. Those remain diagnostic-only and require a new
explicit delegation. There is no blanket auto-labeling or retroactive
promotion. A healthy main with no failing delegated tests correctly leaves
the queue empty; it does not justify synthetic work.


## Discovery: common evidence states, not special-cases

| Source | Structured identity/evidence | Allowed transition |
|---|---|---|
| GitHub Actions failed run/job/step | run ID, workflow, head SHA, failing job/step, URL (the existing daily `dev_autonomy_intake.py`) | diagnostic Issue, **unapproved** |
| A locally reproduced failing fixed test | source path, exact test path/hash, pinned base commit, observed error (`local9b_failure_candidates.py`) | diagnostic Issue with bounded recipe, **unapproved** |
| Open GitHub Issue | canonical number, labels, validated contract, version digest | approved candidate only after the ready gate |
| Open Draft PR and successful/failed CI | PR number, head SHA, exact check conclusion | feedback and verification; never a new execution approval |
| Local worker's result/claim ledger | Issue number, task revision, start, result, delivered Draft reference | consumed, retryable-before-model-busy, or needs human review |

The extraction of an unambiguous source/test pair from CI log syntax is **candidate synthesis only**, not root-cause proof. Any ambiguity means review. No log-provided shell commands, unrelated file scopes or model-written tests become executables.

## Deterministic priority and fairness

`scripts/local9b_task_selection.py` is the sole versioned ordering policy. No LLM ranking, free-text severity estimation or task filename lexical ordering influences execution.

- Explicit GitHub labels `foundation-autodev:p0` through `foundation-autodev:p3`, one at most, set priority P0 > P1 > P2 > P3. With no label, priority defaults to **P2**, not P0. Contradictory priority labels mean `NEEDS_PRIORITY_REVIEW` and the Issue is **not queued**.
- Within a priority, `python-fixed-test` (immutable pinned regression, baseline must fail) precedes the legacy host-defined `bounded-http-positive-limit` smoke recipe. **Both** must pass their own pre-model acceptance gate.
- Within the same priority/evidence class, process **oldest GitHub Issue number first**, avoiding the previous filename / updatedAt hash order and avoiding starvation caused by edits. All ties resolve deterministically.
- A `foundation-autodev:hold` label overrides all priority labels, regardless of P0. Unsupported contracts or uncertain receipts are held for review, not executed.
- Candidate collection failures are reported as `PARTIAL_SUCCESS` while independently approved Issue intake can proceed. One malformed candidate no longer blocks all ready Issues.

The worker now consumes **at most one** approved and unconsumed Issue per five-minute launch. When it succeeds or fails, its result remains bound to that Issue. The **next** launch selects the next eligible Issue. If shared host compute is busy **before** inference, its owned markers are released and that attempt is deferred. All post-model failures or ambiguous crashes preserve the claim and cannot silently loop.

## Boundaries and remaining limitations

This is a **generalized definition of what to select**, not an unlimited ability to solve arbitrary tasks. Today execution supports only bounded host recipes (`python-fixed-test` and the legacy HTTP positive-limit case); future recipe classes require separately reviewed executor/acceptance code and tests. GitHub CI observation, regression candidate production, and automatic execution admission are distinct gates.

Scope is one writable source file and one host-controlled test. No CI log-derived commands, test edits, unapproved services, 4B rework, paid APIs, credentials, merge, deployment, Native effects or production acceptance. Draft PR creation and exact remote source readback remain the output, not a merge decision.

**Acceptance criteria:** model-free focused ordering/approval tests, no regression in prior at-most-once tests, actual M1 source/install readback, and one fresh multi-Issue live queue smoke to demonstrate the second Issue is not lost. No claim of live installed change until that acceptance runs. 
