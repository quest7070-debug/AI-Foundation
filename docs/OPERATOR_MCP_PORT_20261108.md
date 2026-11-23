# Operator MCP guarded tool port — 2026-11-08

Parent: Issue #402 (P3); current main at branch origin `70ead2baadb53512d5dc49f17913fac1a83ca2c2`.

## What this change actually provides

`OperatorMcpTools` is a transport-independent in-process tool interface exposing
`foundation_status`, `approval_requests`, `review_candidate` and
`submit_decision`. It delegates directly to the **existing Operator/Guard**.
It neither creates an approval ledger nor adds an MCP network listener.

A separately verified MCP host adapter must inject an independently
authenticated, non-model-controlled principal and a trusted host-owned
`authorize(principal, tool_name, run_id)` callback. No identity or grant is
taken from tool arguments, HTTP headers, HumanModel text or third-party data.
Missing/unrecognized principal, missing authorizer, or absent exact per-decision
scope fail closed.

The read side suppresses Guard targets, HumanModel source, secrets and raw
task information. It deliberately reports worker runtime and current approved
HumanModel View as `UNVERIFIED` until an independently attested host observation
exists. `review_candidate` indicates only whether a submitted pending request
identity is current; it does **not** infer a recommendation or approve it.

`submit_decision` requires an exact currently visible Guard request reference
and distinct `submit_decision:AUTHORIZE` or `submit_decision:DENY`
authorization. It requires the canonical durable Guard and then executes the
same Operator action, preserving the existing SQLite compare-and-swap,
single-use and stale-plan refusal. A read-only or AI-proposed response cannot
grant decision authority. In-memory legacy run-only approval is disabled.

## Tests and open acceptance gates

Focused synthetic tests cover unauthorized actors, scoped reads, target
redaction, request retargeting, replay, denial, UI/Guard parity and denial of
unbound migrated records. They use real temporary SQLite Guard records and no
models, services, private views or network listeners.

**Status is SOURCE_ONLY until actual MCP transport is independently
authenticated, bound to this interface, deployment approved, and real M1
status/decision/rollback readback accepted.** This port does not update the
production Operator, replace Kandev lifecycle, grant arbitrary shell, authorize
deployment or satisfy Issue #402 P4. Keep P2 live Settings integration separate
unless the same canonical branch is reviewed and tested. Do not bypass the
existing release-specific Human Gate.
