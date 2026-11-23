# KLM fairness-only pinned release — 2026-11-11

## Exact chain and scope

- Installed verified KLM-only release: `398592a317afc18dad7b1e55c3458324bb15889c` (Issue #587 APPLIED, independent research-atom readback #580).
- Tested candidate/data PR #624: `799a1ad8a0584da6e2a852a363e5edfd61454bf8`; exact-host CI #42930065534: 69 focused tests passing.
- Between these commits the **only changed runtime file** is `src/ai_foundation/klm_drive_work.py`, Git blob `0536eea6be8a6f4b5cb2c38870500890065bf4d6`. `scripts/klm_drive_host_tick.py`, existing research-note reader, 9B handler, shared lease, and all other KLM modules have identical blobs. Preserve 900s LaunchAgent, configured roots, Work DB, model and unmodified unrelated services.
- Execution controller `scripts/m1_klm_fairness_release.py` is a fixed one-shot owner-pinned KLM-only cutover adapted from the already accepted #589 controller; independent readback is in `scripts/m1_klm_fairness_readback.py`. Their Git blobs are pinned by the workflow. No new process, model provider, queue, credentials, database, scheduler or workflow running on normal PR events.

## Owner authority and completed cutover (2026-11-11)

This source/CI implementation **is not approval to switch the live LaunchAgent**. A separate owner-authored PR #624 comment must exactly equal:

```text
<!-- foundation-klm-fairness-deploy: {"version":1,"release":"799a1ad8a0584da6e2a852a363e5edfd61454bf8","previous_release":"398592a317afc18dad7b1e55c3458324bb15889c","scope":"klm-only","effects":"launchagent-only"} -->
```

The exact owner comment was recorded at PR #624 comment #6783828525, and the same exact marker was placed in the **owner-authored live PR body**. The runner's Issue-comment API returned HTTP 403; the fixed PR read-only GET checks the exact body marker, owner, base/head, and draft state without widening permissions. A separate exact owner push to `ops/klm-fairness-pinned-release-20261111` with commit message `test(m1): apply pinned KLM fairness release` ran the fixed workflow. The installed-source check is idempotent; `ALREADY_INSTALLED` triggers independent readback rather than a second service switch. Routine pushes/PRs cannot switch the service.

## Safe execution and final E2E

When triggered, check current old plist and immutable installed release blobs, verify new Git SHA and a fixed file list, deny any running KLM Work, acquire existing HostComputeLease, require service idle, stage the new checkout, save original plist as rollback, replace **only** KLM LaunchAgent paths, and re-register with rollback if verification fails. No model inference runs in the release Action. An explicit concurrent Work/lease/tick conflict returns a bounded DEFERRED status, never stops an existing workload.

After an APPLIED release, a separate read-only program checks registered LaunchAgent, source fingerprints, backup integrity, 900-second schedule and preserved unrelated launch settings. Only then is `APPLIED_VERIFIED` supported. The fairness scheduling *behavior* itself requires a later naturally due KLM tick with stable queued-only development evidence; release success alone is not that operational proof.

Rollback remains available through the preserved prior plist. Never replay uncertain parent #555, force stop models, enable paid routes, execute Native, merge main, or claim full Foundation E2E from a green CI.

## Independent installed result

[Final real M1 Action #42937902396](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42937902396) completed `SUCCESS` with `KLM_FAIRNESS_READBACK.status=APPLIED_VERIFIED`: new release SHA exact, 4 pinned source files, 900s LaunchAgent, previous plist rollback preserved, unrelated service settings unchanged, model calls 0, owner-data writes 0 and new DB false. Earlier Action attempts returned HTTP 403 on recording comments; a subsequent run proved the release was already installed before the final independent readback. Actions logs are the authoritative release receipt, mirrored into PR #624 and Issue #562 via the connected GitHub account. Naturally due 600s queued-only fairness behavior remains a separate E2E criterion.
