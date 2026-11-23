# Full-rollout read-only M1 preflight — 2026-11-08

Parent: [Issue #402](https://github.com/quest7070-dev/AI-Foundation/issues/402).

This adds one fixed operation to the **existing** read-only M1 development bridge. It is NOT a production deployment mechanism, a Guard approval, a new scheduler, a private HumanModel tool, or a Native operation. It reuses the established actor/issue/event/main/receipt checks. There is no user-selected command, path, branch or model call.

**Exact owner-authored issue**:

Title: `Foundation M1 Bridge: rollout-readiness`

Body:

`<!-- foundation-m1-bridge: {"version":1,"operation":"rollout-readiness"} -->`

The structured output contains only:

- Current installed Operator entry script and Operator package source SHA **equality labels** against trusted main, if securely readable; hash equality is **not loaded-process proof**.
- Current installed local9B worker SHA equality and failure-intake file presence using the already accepted source-status probe.
- The *existing* HumanModel activation readiness audit's bounded status, owner-binding Boolean, current approved nonempty view verified Boolean and fixed allowlisted blocker codes; never content, path, source, account identity or raw failure text.
- Explicit `release_permitted=false`, `service_mutations=0`, `native_dispatches=0`.

This operation is for deciding the **next exact release contract**, not permission to deploy. Source main integration and an observed healthy service do not license a restart. Stage/release must be separately pinned to the exact approved target, preserve original plist/code and rollback, and pass established owner Human Gate. Run one no-paid 9B autonomous Draft cycle and exact LV2/LV4 HumanModel exceptions only after deployment is independently read back. Do not repeat previously consumed 9B Issues or legacy Native signals.

If installed sources or an approved view are unavailable, the correct result is explicit `UNAVAILABLE` or `BLOCKED`, never a synthetic grant.

Implementation and acceptance: `scripts/m1_foundation_rollout_readiness.py`, `tests/test_m1_full_rollout_readiness.py`, existing bridge issue/receipt workflow. Keep the production installed rollout separately gated.
