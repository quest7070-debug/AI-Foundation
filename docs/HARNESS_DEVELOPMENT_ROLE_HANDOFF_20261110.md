# Harness-managed development loop — role handoff (2026-11-10)

## Responsibilities and dispatch point

The development workflow selects **the next responsibility** at each fixed lifecycle
transition. **Harness selects the permitted inference binding** within the role's
host-owned profile; no Issue or LLM can designate a provider, free/paid route, executable
or credential. All resource/billing eligibility remains under the existing Harness
admission rules. 4B is retired from the development intake path.

| Transition (existing host owner) | Role requested | Inputs from host | Output boundary |
| --- | --- | --- | --- |
| GitHub Issues/CI are observed, before task ranking | `triage` | Bounded observed source keys, existing ready labels, PR status | JSON plan validated against known IDs; cannot grant ready or invoke worker |
| Scoped Issue requires breakdown, before any executor accepts subtasks | `decomposition` | Parent Issue, immutable base SHA, host-approved target/test mapping | Validated proposal only; no new Issue or task authority |
| Approved Issue has passed exact-contract/lease/failing-baseline checks | `implementation` | Immutable task instruction, target source and fixed independent acceptance | One complete replacement source, Guard/Readback checks |
| Fixed test fails after verified source write | `repair` | Same task and scope, test feedback, current source | Next source proposal, bounded by existing max-repair budget |
| Fixed tests pass, before Draft publication | `review` | Exact source SHA, source, fixed test report | Strict PASS/BLOCK bound to SHA; BLOCK vetoes Draft |
| Verified review and unchanged readback | No LLM authority | Existing GitDraftPublisher & independent GitHub readback | Draft PR only; CI and review evidence remain separate |

Approval, scope, trusted test commands, Guard, effect idempotency, Git publication,
post-publish readback and release are **host responsibilities**, not inference roles.
The same LLM can fill multiple logical roles when capacity is limited, but
logical separation is not proof of independent-model review.

## Implementation in this Draft

- `src/ai_foundation/development_harness_roles.py`: reusable owner-bound
  `triage / decomposition / implementation / repair / review` role contract and strict
  source-digest-bound review veto; no new scheduler or provider router.
  The new decomposition helper accepts only host-reviewed file/test pairs,
  requires complete scope coverage and valid dependencies, and returns a
  content-hashed non-executable proposal. No Issue IDs are minted.
- `scripts/dev_autonomy_intake.py`: no 4B or direct Ollama call. The optional
  owner-supplied `FOUNDATION_HARNESS_TRIAGE_CONFIG_JSON` binds a sandboxed DSH
  executable through Harness. If unbound, the existing deterministic
  ready/hold/priority observation runs. Model-generated tasks remain proposals
  only. Invalid Harness replies never become admission.
- `src/ai_foundation/development_loop.py`,
  `src/ai_foundation/coding.py`, `src/ai_foundation/development_host.py`:
  forward optional repair/review roles through the existing Guard/test loop.
  Failed test -> repair agent; passing test -> review gate -> Draft.
- `scripts/local9b_autodev_worker.py`: use the existing local 9B Harness profile
  for implementation and repair by default. An owner-staged, SHA-pinned
  `FOUNDATION_HARNESS_REPAIR_PATCH` and
  `FOUNDATION_HARNESS_REVIEW_PATCH` may bind separate accepted role profiles.
  `REVIEW` is optional until a valid host-reviewed profile is installed;
  no unreviewed or paid fallback and no automatic new model install.
- Targeted synthetic tests cover delegation, repair feedback, review veto,
  digest mismatch, invalid plan IDs, missing Harness bindings and no 4B use.

## Unmet live acceptance (not implied by source CI)

1. Verify a real host-owned DSH triage binding using approved Harness routing,
   and ensure no private GitHub text leaves the approved account/data-egress scope.
2. Verify a separate review profile identity/admission, not merely a second
   prompt against the same 9B. Without it, existing deterministic tests and
   Guard remain mandatory; do not claim independent LLM review.
3. Install the reviewed branch into the existing worker only through its own
   approved deployment mechanism and run one new ready Issue through the
   complete 9B fix -> test feedback -> repair -> optional review -> Draft readback.
4. Record CI/PR feedback, then continue to the next independently approved Issue.
   No speculative main merge, Native signal, paid route, credentials, or
   duplicate worktree/task manager is introduced here.

## Decomposition gap audit (2026-11-10)

Already reusable: scripts/github_task_orchestrator.py validates GitHub Issue
paths, depends_on and overlapping write scopes, then renders read-only
parallel batches. scripts/local9b_issue_bridge.py provides the existing
one-shot Issue claim and fresh approval revalidation. The CODE loop provides
one-source implementation, bounded repair, independent tests and Draft PR.

The new propose_decomposition helper does not create another task queue.
The host supplies a parent Issue, immutable base SHA, exact allowed source
paths and their fixed acceptance tests. The Harness decomposition role may
propose only step IDs, purpose, selected paths and dependency references.
Validation rejects missing or invented targets, duplicate IDs and targets,
dependency cycles, unknown dependencies, and overlapping file writers without
explicit dependency ordering. Acceptance tests remain host-owned.

**Still missing:** a reviewed step-to-existing-Issue or native subtask
admission adapter. The existing 9B worker accepts one pinned source/test
per Issue, and cannot execute these local decomposition step IDs directly.
Live Harness-generated decomposition, work-scope reconciliation, controlled
child acceptance and a real Draft/CI readback are not yet verified.
Neither review PASS nor proposed parallelism grants execution permission.

The Harness triage port also reports HARNESS_TRIAGE_UNAVAILABLE on model-process failure or timeout; GitHub observation and its existing receipt remain available, without an unbounded retry or an invented plan.

## 2026-11-10 executable-contract bridge (Draft only)

- scripts/harness_decomposition_issue_bridge.py now connects a host-bound
  decomposition role to the existing canonical GitHub Issue contract format.
  It re-reads the parent and existing children after model inference and
  revalidates the content-hashed proposal against host-owned source/test
  scope, fixed test SHA256 and host-owned instructions.
- Each ready-to-post candidate contains the existing foundation-autodev
  metadata paths/depends_on and exactly one foundation-autodev-task
  python-fixed-test recipe. The same source/test base SHA and original
  approval are preserved; no model-generated shell commands or file scopes.
- Dependency mappings use actual independently read-back child Issue numbers,
  never model-generated step numbers. Uncreated prerequisites cause a
  WAITING_CHILD_ISSUE_IDS state, not a guessed GitHub link.
- scripts/local9b_issue_bridge.py now checks the exact existing metadata
  write target and requires each dependency Issue to be CLOSED before the
  9B worker queues it. It repeats this check during resolve_task before
  inference, matching the existing GitHub orchestrator's dependency rules.
- The emitted Issue candidate always has empty labels and
  execution_authorized=false. The code here DOES NOT create Issues or
  attach the ready label; that remains a separate GitHub host effect and
  existing admission decision. Draft creation alone is not execution.

The thin GitHubChildIssuePort adapter uses the existing authenticated
GitHubAPI to read the live parent, scan bounded open/closed Issues for the
stable child marker, create one unlabelled Issue, and independently fetch
that exact Issue. publish_next_child_from_github exposes this handoff to
the host without a second queue or provider-specific SDK.

Publication code is also present: publish_one_unapproved_child creates
at most one new diagnostic Issue through the caller's GitHub write port,
re-checking live parent/child evidence before POST and reading back the
created Issue and exact content after POST. It never adds ready or hold
labels. The host must serialize publication and supply complete child
discovery (including closed Issues); uncertain HTTP writes are re-discovered
rather than blindly retried. The code is not installed/activated here.

Remaining acceptance: bind this publisher to the existing host GitHub
writer and running Harness profile, verify one real parent/child readback,
then admit only children that pass current independent baseline/Guard
policy. The 9B worker now checks closed dependencies before model use.
No live multi-agent dispatch or automatic permission promotion is claimed.
Source tests and GitHub Actions are separate from M1 live acceptance.

## Host entrypoint staged (Draft, not installed): reproducible two-phase handoff

`scripts/harness_decomposition_runtime.py` is the bounded host-native entrypoint.
It replaces repetitive model calls with one immutable local proposal receipt:

1. Owner stages a 0600 JSON host config (schema `foundation-harness-decomposition-host/v1`)
   with canonical repository, reviewed parent Issue number, current protected
   main SHA, exact source/test SHA256/instruction pairs, and pinned existing
   sandbox-exec/DSH role argv, Seatbelt profile digest and Harness patch digest.
   The CLI separately receives this config's SHA256. It refuses malformed
   paths, an arbitrary model/command, a missing sandbox or changed file bytes.
2. Run `--preflight` with the same pinned host config. This performs only
   HTTPS GitHub reads and local pinned-file validation (no DSH, no model, no
   child Issue POST); it checks current protected main, existing source/test
   hashes and the live parent's ready/hold labels and exact file scope.
   Any mismatch stops before allocating model compute.
3. Preview with `--stage-plan` invokes only the admitted Harness
   decomposition role. It independently fetches current main via GitHub,
   verifies every source path exists and each fixed pytest blob matches
   the host pin, then checks the parent ready/hold state and all known
   children. A new proposal is written once (O_EXCL, 0600, fsync) beside
   the owner config. The CLI returns a content SHA256 for the receipt.
4. Each later `--publish-one` **requires** `--proposal-file` and
   `--proposal-sha256`; no LLM is invoked. The host re-verifies the current
   main and pinned test blobs, then rereads the parent/children, creates
   at most one Issue with no ready label and checks exact remote body
   readback. A host-local flock serializes same-host publishers. The
   existing GitHub Issue planner and one-shot 9B worker own downstream
   dependency/ready/Guard admission. There is no new scheduler or DB.

Example host-side invocation shape (paths/digests come from an accepted
host-owned config, never from GitHub Issue text):

    python3 -B scripts/harness_decomposition_runtime.py \
      --host-config /approved/private/decomposition-host.json \
      --host-config-sha256 <verified-host-config-sha256> \
      --stage-plan /approved/private/decomposition-plan.json

    python3 -B scripts/harness_decomposition_runtime.py \
      --host-config /approved/private/decomposition-host.json \
      --host-config-sha256 <verified-host-config-sha256> \
      --proposal-file /approved/private/decomposition-plan.json \
      --proposal-sha256 <staging-output-plan-file-sha256> \
      --publish-one

The runtime holds the existing HostComputeLease around only the
Harness decomposition inference turn; when M1 compute is owned elsewhere it
defers without evicting a model or falling back to a different provider.
Preflight and pinned-plan child publication never acquire inference lease
because neither calls an LLM.

The runtime keeps GitHub_TOKEN/cloud API tokens out of the DSH child process,
pins HOME and DSH_HOME to the private host directory, refuses an inherited
non-loopback OLLAMA_HOST, and uses only the pre-reviewed Seatbelt/patch.
These structural checks DO NOT independently prove that a saved Harness
profile cannot use metered routing; before any real model call the host owner
must separately verify the active profile is LOCAL_ONLY/zero-charge and
that the private DSH_HOME contains no metered-provider fallback.

**Limitations:** no approved multi-file parent is currently bound here;
no host config or private profile was installed or changed, no real DSH
inference turn was run, and no real GitHub child Issue was created. Local
flock does not provide cross-machine atomic GitHub POST, so a host owner
must not run competing publishers on other machines. If an HTTP POST has
an uncertain outcome, rediscover children first instead of blindly retrying.
Dependent child task contracts remain pinned to the same base SHA; parent
closure alone does not prove that preceding Draft changes are integrated.
Any live dependency-sensitive execution must independently establish the
correct base/acceptance state before granting ready, otherwise defer.
These are live acceptance gates, not statements of completion.

After the host config is staged, use this read-only acceptance first:

    python3 -B scripts/harness_decomposition_runtime.py \
      --host-config /approved/private/decomposition-host.json \
      --host-config-sha256 <verified-host-config-sha256> \
      --preflight

CLI preflight is not a substitute for admitted model route evidence, a
failing acceptance baseline, reviewed child approval or live Draft/CI E2E.

## Existing approved Issue backlog: real M1 read-only preflight

Do not invent a multi-file parent to run a synthetic example. The real
approved and unconsumed-by-GitHub-state queue includes individually scoped
9B task Issues #266, #270 and #271, each on a pinned `local9b/...` branch.
They are already accepted single-source development intents; the new
multi-file parent adapter (main-only) must NOT rewrite their authorizations.

`scripts/local9b_real_issue_preflight.py --issue 266 --issue 270 --issue 271`
uses the existing `local9b_issue_bridge.issue_task` contract parser and
selection admission, the same GitHubAPI and independently fetched branch
commit, source and test contents. It checks SHA256 test pins, fresh ready
labels, hold/priority state and dependency closure. The read-only
`m1-approved-issue-preflight` Actions job uses the existing self-hosted M1
runner with `contents:read` and `issues:read`, and zero model-related
permissions or commands.

Success means only `PINNED_READY_ISSUE_VERIFIED_NO_EXECUTION`.
It does NOT establish local one-shot receipt state, failing baseline,
model availability, current deployed code, actual 9B inference, code
repair, review or a remote Draft PR. These still require the existing
reviewed M1 worker and its independent acceptance/readback. Native
Issue #35 is explicitly not a 9B python-fixed-test candidate.

## 2026-11-10 P4 installed-layout correction and consumed Issue quarantine

The first M1 bridge #540 `OWNER_FILE_MISSING / RESULT_DIRECTORY` was
**a diagnostic false assumption**, not proof that 9B receipts were lost.
Production P4 [PR #470](https://github.com/quest7070-dev/AI-Foundation/pull/470)
had already APPLIED a versioned immutable code release while preserving the
original owner queue under the *host-owned* launchd
`AI_FOUNDATION_LOCAL9B_STATE_ROOT`. Its independently accepted
`m1_p4_live_readback.py` checked that previous inbox/results were retained.
The unmerged main runtime-status source still inferred `worker.parent`.
The accepted P4 `_worker_root` code is reused unchanged here for legacy
and P4 LaunchAgent modes, preserving owner/symlink checks. The fixed
source-status allowlist now fingerprints `repo/src/ai_foundation/` when a
P4 release package is present rather than falsely requiring legacy
`modules/ai_foundation/` beside the new worker executable.

New `local9b_installed_layout_probe.py` observes the two separate
owner-bound code/state roots, checks only fixed source/dependency and
inbox/results metadata, and outputs no path or file contents. Synthetic
tests cover both legacy and P4 distributions and a missing/untrusted
queue state root. `m1-worker-layout-diagnosis` reads this on the real M1.

Existing approved Issues #266, #270 and #271 were *already consumed*.
Published evidence: #266 -> Draft #267, #270 -> Draft #275, #271 ->
`REPAIR_BUDGET_EXHAUSTED` (documented by PR #281). Each received
`foundation-autodev:hold` on 2026-11-10 to prevent accidental replay
while the observed legacy-vs-P4 path discrepancy is reconciled.
The read-only preflight CI now verifies these live holds rather than
calling a ready-label check an executable task. Holds do not rewrite
original results, clear claims or grant new execution authority.

Fresh E2E candidate is **Issue #476**, not a replay of #266/#270/#271.
Actual historical P4 task Issue #476 **already completed** its fresh
post-release 9B E2E: accepted independent M1 receipt at
https://github.com/quest7070-dev/AI-Foundation/issues/476#issuecomment-6737082302
and real Draft PR #479 (open/draft, HEAD a5d55f79), with pinned fixed-test
source-only change and Foundation CI #42595302130 SUCCESS (2165 passed).
Do not restart #476 or reimplement its P4 one-shot receipt reader.
The originally proposed redundant CI re-read was removed. This is
existing 9B worker E2E proof, **not** a live E2E of the new Harness
decomposition/triage/role-dispatch path. Neither path was newly invoked here.

## Independent child automatic handoff (2026-11-10)

Before this change the decomposed child could only be published as an
unapproved Issue, despite its host-reviewed parent already having the
`foundation-autodev:ready` label and exact source/test pins. There was
no last-mile handoff to the existing 9B intake without manually applying
ready to every child.

The existing host-bound `harness_decomposition_runtime.py` now exposes
`--admit-one` using the same original host config SHA and immutable
`--proposal-file` + `--proposal-sha256`. It is a separate one-effect mode
from `--publish-one`, under the same local publication mutex:

    python3 -B scripts/harness_decomposition_runtime.py \
      --host-config /approved/private/decomposition-host.json \
      --host-config-sha256 <verified-host-config-sha256> \
      --proposal-file /approved/private/decomposition-plan.json \
      --proposal-sha256 <staging-output-plan-file-sha256> \
      --admit-one

On every admission the owner checks the protected main HEAD, fixed test
SHA256, parent still open with ready and no hold, exact host-reviewed
scope and exact content-hashed child body against GitHub. The admission
labels at most one existing open **independent** child ready; it does
not create new tasks, run a model or bypass 9B's fixed acceptance and
one-shot claim policy. Child tasks with any cross-step dependency are
left unapproved even if their predecessor's Issue is closed, because
closed Issue / unmerged Draft does not prove its source was integrated
into the common base. The parent remains the only inherited execution
authority and cannot nominate arbitrary new paths/models/tests.

This is source and synthetic GH-port acceptance only. There is no
live eligible multi-source parent Issue, staged owner config or actual
Harness decomposition profile observed in the repo. It cannot be
called a new real Harness E2E without such a parent, live role turn,
ready child execution, final Draft and independent readback.

### Pinned review branch, not a moving main assumption

The host config may optionally include `"base": "local9b/<reviewed-branch>"`
(default `main` for compatibility). The existing `local9b_task_recipe` and
worker already accept this bounded branch family. The decomposition model
still sees only the exact base SHA, source/test paths and no provider grants.
Before any inference, child publication or ready projection the host
fetches the chosen GitHub branch's current commit and requires it to match
`base_sha`; fixed test bytes are fetched at that exact SHA. The emitted
`python-fixed-test` child contract uses this same host-owned branch name
and SHA. Unrelated main updates no longer invalidate an in-progress
reviewed multi-source task, while a moved reviewed branch still blocks.

This does **not** rebase or integrate dependent child Draft PRs.
Dependent tasks remain unapproved until their actual source ancestry
and acceptance are independently established by a later reviewed flow.

## Real two-source Harness parent #555: M1 verified input and bounded stage

- [Issue #555](https://github.com/quest7070-dev/AI-Foundation/issues/555) is a real, independently reproducible **approved parent only**. Its branch `local9b/harness-two-source-red-20261110` at `b752bab66841ed0ee9f401bf12532132c003cb74` was created from fixed main `48e9bb44`; GitHub comparison confirms only two new fixed regression tests, unchanged source.
- Actual [M1 RED evidence in Actions #42751188030](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42751188030): 4 tests run, exact two known failures (Agent None stringification, empty fixed-test feedback leading to Draft), two normal controls PASS, no import/infrastructure failures, no model or GitHub writes. SHA256 pins for exact test/source bytes are in the Issue.
- [M1 host asset preflight in Actions #42752019221](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42752019221): parent `PRE_MODEL_VERIFIED`, 2 exact source/test pins verified, P4 owner-private profile present, existing DSH executable, Seatbelt pinned, local `qwen3.5:9b` budget patch matched; shared 11434 alive, dedicated 11436 not started. Read-only: no model or file/Issue mutations.
- Actual Harness `decomposition` inference previously received only filenames, insufficient to deduce fixes. It now additionally receives **only** host-pinned `instruction` per source, under the same exact path validation. These descriptions never change execution authority, code target, tests or model selection.
- Added `scripts/m1_harness_parent555_stage.py`: **fixed one-parent, one-shot** owner M1 stage. It checks exact-head Foundation CI success, parent scope, source/test SHA, pinned P4 seatbelt/DSH/profile and existing HostComputeLease, starts only an owned dedicated 9B backend when the shared model is idle, stages one private immutable plan receipt, and terminates only its own backend. No cloud keys passed to DSH; no 4B; no `SIGKILL`, model eviction, Native effect, child creation, auto-ready, scheduler, merge or deployment in this phase.
- An unavailable lease or incomplete CI returns explicit `DEFERRED_*` and does not run the model. Missing assets, divergent owner receipt or invalid plan fail closed. Completed stage receipts suppress repeated model turns. `m1-harness-parent555-stage` runs only on the owner-authored PR #524 and still needs real live acceptance.
- **The first full role E2E is not accepted until** an actual `PLAN_STAGED` from local qwen3.5:9b, frozen plan SHA independently recorded, child Issue creation/readback and independent child ready into existing worker, followed by actual Draft delivery and review/readback. Passing M1 RED/source-only tests is not a substitute.

### 2026-11-10: transient compute contention must not abandon staging

Actual M1 run [#42753549494](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42753549494) completed its stage job but emitted `DEFERRED_COMPUTE_BUSY` (no model call, no plan). That is a scheduling deferral, **not** an E2E pass. The first stage entrypoint returned immediately on `HostComputeBusy` and a completed PR workflow did not automatically resume when the host became idle.

`m1_harness_parent555_stage.py` now retries only `HostComputeBusy` and `DeferredCiNotGreen` on the **same CI job** at 30-second intervals for up to 600 seconds. The host lease is reacquired each attempt; shared Ollama occupancy and the dedicated loopback backend are checked again, without evicting or terminating another model. The same immutable plan receipt is always read first; neither model failures nor uncertain GitHub/filesystem effects are retried. The dedicated CI job now reserves 32 minutes to fit the bounded wait plus the already reviewed 900-second inference cap. Unit tests check transient busy→availability, CI readiness, exhaustion and refusal to repeat unknown errors.

**Limit:** This is a bounded in-job retry, not a new persistent scheduler. If the resource remains occupied for all ten minutes, the job returns explicit `DEFERRED_COMPUTE_BUSY`, never `PLAN_STAGED`. Automatic recurrence beyond the current PR run would require connecting the existing durable operator/LaunchAgent intake after a separately verified deployment; it is not silently claimed here.
