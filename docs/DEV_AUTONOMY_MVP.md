# Development Autonomy MVP

> **2026-11-12 current owner clarification:** The historical Stage-1 numbered
> loop below is not a live execution recipe. `SYSTEM_ROLE_BOUNDARIES.md`
> supersedes Paseo ownership in steps 5–6: GitHub/Foundation Guard/Harness
> own the admitted loop, and the installed finite local9B worker handles
> approved ready Issues and standing-delegated main regressions. DSH→OpenCode
> and Codex OSS are optional frontends. Do not re-enable 4B or legacy Native
> installer paths based on this history.
>
> **2026-11-10 replacement policy (PR #524):** The 4B-only planner below is
> historical and no longer the active design. Active intake uses GitHub
> observation with an optional host-bound **Harness triage role**; the
> implementation, repair and review roles are separate Harness ports at their
> lifecycle boundaries. Model/provider selection is owned by Harness and the
> approved host profiles, never by Issue text or this intake script.
> The original 4B entries and historical blocked Native status below are
> retained as an implementation history, not current execution instructions.
> Canonical implementation: `docs/HARNESS_DEVELOPMENT_ROLE_HANDOFF_20261110.md`.

Status: **MVP implementation in progress**. This document records the execution boundary for the first GitHub-driven development loop.

## Intended loop

1. Observe GitHub open Issues, recent failed workflow runs/jobs, and open PRs.
2. Use only the M1 loopback Ollama endpoint and the pinned qwen3.5:4b model to rank known signals and propose dependencies/parallel lanes.
3. Record one bounded daily report on Issue #7 and a short-lived, redacted workflow artifact.
4. Keep GitHub Issues/PRs as the canonical task, dependency, and evidence surface. Do not introduce a second task database.
5. After the source-reviewed Paseo task contract and isolated M1 worker gate are verified, hand explicitly approved intents to the Paseo Development lifecycle.
6. Paseo owns development task/session/worktree/subtask/dependency/executor lifecycle and recovery. GitHub Issues/PRs/Actions remain the canonical source-control and evidence surface; Foundation owns Canon/Guard/policy/evidence and independent verification. Kandev remains frozen legacy and is not used.
7. Merge, release, permission, credential, billing, and production operations remain explicit Human Gates.

## Current implementation slice

scripts/dev_autonomy_intake.py provides a read-only intake and planning adapter. It:

- Reads bounded pages of open GitHub Issues, recent failed GitHub Actions runs plus failed jobs/steps, and open PR metadata.
- Treats issue/PR/workflow text as untrusted data, not instructions.
- Calls only http://127.0.0.1:11434/api/chat using the allowlisted local model qwen3.5:4b; it has no cloud/model fallback.
- Requires the model to return a strict JSON plan referring only to observed source keys.
- Rejects unknown/duplicate task references and invalid/cyclic dependencies.
- Labels a candidate only when the source Issue carries foundation-autodev:ready and the model ranks it low risk. This is a prioritization hint, not execution authority.
- Persists no raw Issue descriptions or model-generated rationale in the report artifact/comment.
- Converts observed CI failures into deduplicated GitHub Issue repair drafts using workflow ID, exact commit SHA and failed-job/step set as the stable identity. Drafts contain evidence links and diagnostic observations only; no root cause is invented.
- Never applies the foundation-autodev:ready label to generated drafts. A human must add that label before a draft becomes eligible for planning. Existing ready issues remain only prioritization candidates, not execution authority.
- Never dispatches a Foundation Native task or starts a worker, creates a branch/PR, merges, changes permissions, or deploys.

.github/workflows/dev-autonomy-intake.yml runs deterministic tests for source changes and schedules the local-only daily intake on the M1 runner at 22:00 UTC (approximately 07:00 JST). The report is upserted on Issue #7 using a bot-owned comment marker; it does not open a new Issue each day.

## Canonical ownership

- GitHub is the canonical project/evidence surface.
- AI Foundation supplies the objective, policy, Canon/evidence requirements, and independent completion criteria.
- GitHub Issues/PRs and Actions are the canonical source-control and evidence surface.
- Paseo owns the new isolated development task/session/worktree/subtask/dependency/executor lifecycle. GitHub Issues/PRs/Actions are the canonical source-control and evidence surface. Foundation must not add a competing development task database, scheduler, worktree manager, or worker supervisor.
- Do not add a parallel task database, scheduler, or second Native/session manager inside Foundation.
- Parallel work is allowed only after a decomposition proves disjoint write scopes. Shared Canon, integration points, policy, acceptance tests, and release changes are serialized.
- Test/repair attempts must be finite and evidence-driven. Repeated equivalent failures become BLOCKED/NEEDS_HUMAN rather than an infinite restart loop.

## Current blocker before autonomous dispatch

The remaining blocker is the Paseo Native task-admission contract. The current host hook `deploy/paseo-foundation/m1_reviewed_host.py::_reviewed_pi_startup_contract()` remains fail-closed until the exact source-reviewed task pin, fresh signed Gateway original, one-shot Human Decision, and task-specific kernel write boundary are accepted. The event-driven planner and local Ollama report are read-only and cannot bypass this gate.

Before dispatch, bind the canonical GitHub Issue/PR intent to the exact owner/original/payload digest, repository/Canon base, Native calls/effects, independent acceptance test, and current M1 host evidence. Keep model credentials and GitHub write credentials outside the model-facing process; use Paseo's isolated task/worktree lifecycle, bounded retries, stop/readback, and independent verification. PR-head code must never run inside the trusted event workflow. Until those gates exist, PR #11 remains report-only and worker execution stays disabled.

Separate gate: PR #8's direct Paseo Native path still returns None from _reviewed_pi_startup_contract(). The existing local-route reader/LocalExecutionAttestation is present, but no exact source-reviewed task pin, fresh signed Gateway original, or one-shot Human Decision is registered. PR #11 does not bypass or replace that gate.

## Promotion gates

| Slice | Required evidence | Current status |
|---|---|---|
| GitHub intake | deterministic tests; bounded Issues/Actions/PR readback | source implemented; CI pending |
| Local planning | M1 loopback Ollama model readback; strict plan validation; no cloud fallback | local model and zero-charge route observed; live planner call still to verify |
| Daily report | idempotent bot-owned Issue #7 report; report contains no raw Issue bodies | workflow added; first scheduled/manual run pending merge |
| Paseo Native dispatch | exact source-reviewed task pin; signed original; one-shot Human Decision; isolated M1 write boundary | blocked on source-reviewed Paseo task admission and M1 write boundary |
| Parallel workers | Paseo native subtasks/worktrees; disjoint-write contract; one writer per shared scope | not enabled yet |
| Test & repair | bounded retry budget; exact CI/job/step correlation; safe continuation and stop | not enabled yet |
| PR review gate | independent review + deterministic checks + acceptance test integrity | GitHub PR/CI gates remain the authority |
| Test & repair | bounded retry budget; exact CI/job/step correlation; safe continuation and stop | not enabled yet |
| Merge/deploy | explicit human approval and protected-branch/release gate | disabled |

## Operational limits

- Zero additional inference cost is the default. No metered cloud provider is used by this workflow.
- GitHub API reads and the one Issue #7 bot comment use the repository's normal GITHUB_TOKEN; no PAT is created or stored.
- No credentials are sent to Ollama.
- The plan model cannot select an unobserved Issue, mint task IDs, or authorize an execution.
- The report is an observation artifact, not a completion claim. CI failure task drafts are canonical GitHub Issues, but remain unapproved until a human adds the ready label.
- The workflow is not a 24/7 mutation loop. NO_CHANGE, WAITING_FOR_PASEO_NATIVE_WORKER_GATE, and NEEDS_HUMAN are valid outcomes.
