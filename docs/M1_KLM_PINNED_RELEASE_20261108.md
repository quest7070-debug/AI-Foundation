# Pinned M1 KLM-only release — 2026-11-08

This workflow does not modify the read-only M1 development bridge. It is a separate one-release GitHub Actions route, with exact SHA, old generation, target label and source blobs compiled into trusted default-branch code.

**Target:** repository quest7070-dev/AI-Foundation. Prior installed release `5688bd24f098d99886a0e489331160de99ac8de2`; new code `71a74d9bb065585a368167c34139263e7e59cc7c`, merged into the stacked KLM PR #301 branch only. Its M1 postmerge CI [#42386565718](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42386565718) passed 1,783 tests. The single affected service is `dev.quest7070.ai-foundation.klm-drive` with its existing 900-second interval.

**Trigger:** After this exact source/CI is merged to default main, an owner-authored GitHub Issue titled `Foundation KLM pinned release: 71a74d9b` with body exactly:

`<!-- foundation-klm-pinned-release: {"version":1,"release":"71a74d9bb065585a368167c34139263e7e59cc7c","scope":"klm-only","intent":"2026-11-08-owner-request"} -->`

The source rechecks the live issue and receipt before any host change. No Issue values become shell commands, paths, model routing, scopes or commit identifiers. The only allowed requested effect is this fixed code version. It requires the actual owner M1 session, unmodified old script/handler SHA, Git branch/target SHA equality, existing development-idle decision, original HostComputeLease, no RUNNING or PLANNED KLM Work, no competing Ollama/llama-server inference and inactive KLM launchd job. It stages only the versioned KLM release and atomically switches the KLM LaunchAgent script/PYTHONPATH, after saving the exact previous plist under mode 0600; it rolls back on any bootstrap or readback failure. Repeated requests against already-installed SHA do not restart the service.

No paid service, private Drive values, model text, secrets, Native/Guard/Operator effect, other LLM change or mass FAILED Work requeue is included. The only GitHub audit receipt exposes a small fixed status, release SHA and label. Verify the result separately with the existing read-only `klm-status` and `runtime-status` operations. Remove this one-shot workflow after verified cutover to avoid permanent deployment privileges.

The separate Kandev request was pending and is not used; Desktop Commander is also unused.


## Second reviewed KLM lifecycle release (2026-11-08)

The previous one-shot workflow was removed after its successful Issue #355 `APPLIED` receipt and later Issue #358 readback. The earlier running release was `71a74d9bb065585a368167c34139263e7e59cc7c`.

Owner requested deployment of the new lifecycle implementation in Draft PR #301:

- Exactly pinned new SHA: `369e74a4f8a9f19f369aa182f865b2d8fadb57c0`.
- Real M1 source CI #42405312687: success, 1,793 passed / 15 skipped.
- Immutable handler, launch script, lifecycle store, Drive cycle, worker and new projection files have independently recorded Git blob IDs in `scripts/m1_klm_single_release.py`.
- This is a KLM-only release; it does **not** authorize Guard, Operator, Native or HumanModel changes, or any owner-projection write. The new runtime projection entry point is not connected to periodic writes.
- Old plist backup and KLM-only label/cadence checks are mandatory. The exact prior `71a74d9b` release must still be installed, otherwise fail closed.
- Strict GitHub Issue title: `Foundation KLM pinned release: 369e74a4`.
- Exact body: `<!-- foundation-klm-pinned-release: {"version":1,"release":"369e74a4f8a9f19f369aa182f865b2d8fadb57c0","scope":"klm-only","intent":"2026-11-08-owner-request"} -->`.
- Separate one-use workflow `.github/workflows/m1-klm-pinned-release.yml`, no generic shell. Delete its workflow file after an independently verified `APPLIED` receipt.
- Deployment CI proves source syntax and fixture compatibility, not real live 9B failure recovery or P3 owner writes. Real Work and zero-effect audits require separate acceptance.
