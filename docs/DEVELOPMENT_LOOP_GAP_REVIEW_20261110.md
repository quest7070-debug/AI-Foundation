# Development loop gap review — 2026-11-10

## Observed boundaries

Canonical repository: `quest7070-dev/AI-Foundation`.
This review uses the current `main` source and open Drafts; it does not
confuse source-ready and installed/accepted behavior.

| Stage | Evidence | Remaining gap |
| --- | --- | --- |
| Intake / diagnosis | `scripts/dev_autonomy_intake.py`, `scripts/local9b_failure_candidates.py` | Recent CI failures became many unapproved Issues, often for successive commits of one branch. The daily intake still required 4B even though selection and execution are model-independent. |
| Approval / selection | `scripts/local9b_task_selection.py`, `scripts/local9b_issue_bridge.py` | The worker accepts only exact ready Issues with finite supported contracts and single-shot claims; broader ordinary coding tasks are not automatically admitted. |
| Fix / verify | `src/ai_foundation/coding.py`, `src/ai_foundation/development_host.py`, `scripts/local9b_autodev_worker.py` | A bounded test/repair mechanism exists, with a restricted fixed-test recipe. General multi-file safe repair, test-failure taxonomy and broad fresh-issue E2E are not proven. |
| Draft / feedback | `src/ai_foundation/development_git_delivery.py`, `docs/LOCAL9B_TASK_SELECTION_POLICY.md` | Draft publication does not imply CI acceptance, code review, owner-approved merge or automatic new implementation authority. A consumed Issue is deliberately not replayed. |
| Continuous progression | Five-minute existing local worker, standing delegation for three exact main/test pairs | A completed Draft does not create an arbitrary next task. Only an independent new ready Issue or explicitly delegated reproduced regression can enter the queue. |

## Implemented here

1. **Model-free scheduled intake:** `scripts/dev_autonomy_intake.py` defaults to deterministic triage based on observed ready/hold/priority labels. An explicit `--planner local-ollama` retains the old read-only planner for focused diagnostics; daily automation does not call it.
2. **No 4B contention:** `.github/workflows/dev-autonomy-intake.yml` removes the 4B model inventory precondition and host compute lease around a network-only GitHub observation. Existing 9B worker, approvals and task execution are unchanged.
3. **CI feedback coalescing:** a diagnostic Issue is reused for successive failed heads of the same (workflow ID, branch), with a stable thread marker, bounded links to prior runs and fresh read-before-write. Only bot-authored, pristine legacy diagnostics are adopted; newer generated bodies include a verified content digest. Exact repeats are idempotent; a newly approved, held, human-edited or closed Issue is never overwritten. No auto-ready labels.
4. **Ready-Issue completeness:** fetch ready-labeled open Issues independently before the newest diagnostic backlog, deduplicate by Issue number, and refuse an overfull ready scan rather than silently losing work at the report cap.
5. **Current-CI-only feedback:** newer successful/pending runs suppress stale workflow/branch failures, and the latest diagnostic identity cannot be overwritten by an older signal on a later tick.
6. **Focused regressions:** deterministic selection/hold/priority, ready-Issue precedence under 50+ diagnostics, CI legacy adoption, idempotency, approval-race refusal and stale failure suppression.

## Deliberately not activated

No model call, task creation, ready-label promotion, new entitlement/Guard policy,
Native signal, main merge, test rewrite, release, paid provider or external account
change is authorized by this patch. GitHub API mutations are limited to *existing*
scheduled publication of diagnostic Issues and reports. The patch changes how
diagnostic Issues are consolidated, not what counts as a runnable task.

## Next bounded acceptance

- Run `python3 -B -m unittest discover -s tests -p 'test_dev_autonomy_intake.py'` on the exact Draft head, then verify current CI.
- Confirm one scheduled intake observes ready Issues and publishes/upserts an Issue #7 report without invoking 4B.
- Independently verify a new, delegated 9B Issue completes test-failure → repair → fixed test → Draft PR and remote readback on the installed worker. This is a separate live acceptance gate, not proven by these unit tests.
- After that, extend the finite standing delegation through reviewed host recipes and fresh failing baselines; do not convert arbitrary CI text into execution permission.
