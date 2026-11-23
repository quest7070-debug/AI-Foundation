# GitHub-first Foundation auto-development — Stage 1 (historical planner contract)

> **Current implementation note (2026-11-12):** The sections below document the historical Stage-1 read-only GitHub planner and optional legacy Native handoff. They do **not** describe the entire current development loop. The current host uses `scripts/dev_autonomy_intake.py` for observation/diagnostic coalescing, `scripts/local9b_issue_bridge.py` and `scripts/local9b_autodev_worker.py` for exact ready-Issue admission and bounded repair/Draft, and the existing standing-delegation path for three independently reproduced, preauthorized main regression pairs. A diagnostic Issue alone never grants execution. The trusted host/Guard/Harness may proceed within an already approved finite scope; new scopes, paid routes, private egress and production cutover still require their own authority. The former Kandev/Paseo default ownership is superseded by `SYSTEM_ROLE_BOUNDARIES.md`. Source wiring does not prove installed M1 end-to-end completion. See `DRIFT_RECONCILIATION_20261112.md` and `PR_CONSOLIDATION_20261112.md` for outstanding evidence.

This workflow is event-driven, not cron-polled. It recomputes a read-only plan when Issues, PRs, the canonical Foundation CI workflow, check suites, or main change. GitHub event delivery is near-real-time; it is not a permanently resident daemon.

PR lifecycle events use `pull_request_target` so the workflow definition and planner run from the trusted default branch. The job explicitly checks out `main`; it must never check out or execute code from the triggering PR head. Keep the job's GitHub token read-only.

## Explicit opt-in

Only Issues or PRs carrying `foundation-autodev:ready` enter the eligible queue. Issue metadata may specify repository-relative file locks and closed Issue dependencies:

`<!-- foundation-autodev: {"paths":["src/a.py"],"depends_on":[123]} -->`

Unknown or malformed metadata blocks the task. Unknown file scope is exclusive. Overlapping parent/child paths serialize. CI failures are considered only for the current open-PR head SHA and only when explicitly opted in.

## Stage boundary

The current worker is a read-only discovery/planning step. It does not execute task text, run PR code, edit files, create branches, create PRs, approve, or merge. Candidate parallel batches are plans, not launched workers. The bounded plan is rendered to the job summary; the candidate manifest is written only to the runner's temporary workspace. Neither is uploaded as an Actions artifact. The M1 host consumes the current ready Issue directly and independently revalidates it. Candidate manifests remain untrusted evidence, not execution authority.

Next: connect a host-reviewed task contract to isolated M1 worktrees and the already existing local Ollama/Pi route; then add bounded test/repair and independent PR review. Main merge, Native/M1 promotion, credentials, policy changes, and external effects remain approval-gated.


## Native handoff candidate bridge

A ready Issue may optionally include a `native_handoff` object in the existing metadata comment:

```json
{
  "paths": ["src/task.py"],
  "depends_on": [],
  "native_handoff": {
    "anchor": "Exact issue text describing the reviewed task",
    "target": "src/task.py",
    "calls": [["client.createSession", ["create-session"]], ["session.startTurn", ["run-session"]]],
    "acceptance_paths": ["tests/test_task.py"]
  }
}
```

The trusted default-branch planner rejects duplicate JSON object keys (including nested duplicates), whitespace-only or non-matching anchors, and validates one relative target, the reviewed Native call sequence (`client.createSession` then `session.startTurn`, optionally preceded by `client.construct`), unique per-call effect IDs, and fixed independent test paths. This mirrors the current reviewed M1 host operation vocabulary; it does not select a target or call set for the host. It emits a `native_handoff_candidates` manifest only for Issues explicitly labeled `foundation-autodev:ready`. The manifest is a candidate packet, not a task contract or authority: the M1 host must still independently verify the live Issue, fresh signed original, historical replay exclusion, Git/Canon identity, target file, test blob pins, and exact source-reviewed digest. No workflow dispatch, Native task creation, worker, write, or approval is performed by this bridge.


## Moving a candidate to the reviewed M1 host

The event workflow does not upload a candidate artifact. On the reviewed M1 host, use `scripts/m1_pi_native_task_contract_generator.py --live-issue-candidate` with the exact open Issue number. The generator fetches the current Issue from GitHub and independently validates owner authorship, ready label, metadata anchor, target, Native call sequence, acceptance paths, fresh signed original, replay history, Git/Canon identity, and immutable acceptance-test blobs. No artifact download is required; the result remains `REVIEWED_TASK_CONTRACT_STAGED_NOT_AUTHORIZED` and does not create or execute a Native task.
