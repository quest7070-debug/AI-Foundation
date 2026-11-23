# Harness full-source proposal compilation — 2026-11-07

**Parent:** Draft PR #281, latest source starting at `48ee7a22cdd3bbc1cb513b92c7d2d0244fe82b49`.

## Evidence-backed defect

The real M1 owned local9B self-development task #271 produced the final terminal
receipt `REPAIR_BUDGET_EXHAUSTED` after two attempts. The host test recorded:
`GENERATED_SOURCE_SYNTAX_ERROR: 'return' outside function
(notification_boundary.py, line 32)`.

`HarnessProposalAgent.run` accepted the entire generated Python source with
`ast.parse(source)`, but `ast.parse` does not reject `return`/`break`/
`continue` outside their legal blocks or `yield` outside a function.
Therefore invalid but parseable code can reach Guard's write port, requiring
the fixed acceptance test to spend time diagnosing source the host could have
rejected before any write.

## Surgical repair

After the existing strict JSON-decoding and `ast.parse`, call
`compile(source, "<harness-proposal>", "exec")` **without executing
it**. This checks Python's contextual compile-time validity before any guarded
filesystem modification. The original literal-only guard and complete-source
requirement remain in place.

The existing `run_development_loop` already catches `SyntaxError`
from `agent.run` and provides `PROPOSAL_SYNTAX_ERROR` feedback to its
next bounded turn. No new repair budget, model, token cost, retry loop, branch
write or process is introduced.

## Independent test

`tests/test_local9b_harness_compile_preflight.py` uses a synthetic fake
Harness subprocess; it performs no real model call or file write. Its
reproduction against unchanged parent produced **4 failed / 3 passed** on
real M1 at `45e0b42bb8c801e358862ad8bc3f57c8638f4d15`:
four invalid module-level control-flow forms escaped compile-time checking
(or hit the weaker literal-only error). Valid function returns, valid source
that would perform an effect if executed, and literal-only rejection form the
unchanged behavior tests. The production fix is one pure `compile` call.

**Boundaries:** this catches syntactically/contextually invalid Python, not
incorrect semantics or a guarantee of 9B task success. Independent full CI
and real 9B end-to-end accepted results remain separate gates.
No live LaunchAgent is modified; no Native Issue #35 or KLM PR #283/#284
code is touched. Paid provider/alternate model use remains prohibited.

**Decision:** source-only guard pending CI, not deployed.
