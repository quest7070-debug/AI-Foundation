# Agent Skills implementation checkpoint (2026-11-10 JST)

Status: DRAFT CODE / NO MAIN MERGE / NO REAL M1 ACCEPTANCE.
Plan: docs/AGENT_SKILLS_WORKFLOW_PLAN_20261110.md; PR #553; Issue #554.

## P0 — actual code ownership check

| Source | Existing owner/behavior | Action |
| --- | --- | --- |
| src/ai_foundation/auto_agent.py | Pydantic AI owns normal tool selection and sequential tool use | Add only optional read-only procedural reference |
| scripts/operator_server.py | Trusted host composes request and Agent | Reuse its factory, never create a second Agent |
| src/ai_foundation/capability_request.py | Host-scoped CODE/FILES/DATA/COMPUTE grants | Unchanged; skill text cannot grant a capability |
| src/ai_foundation/capability_composition.py and mcp_capability.py | ToolHive and bounded MCP tools | Unchanged; no new server |
| docs/BOUNDARIES.md and docs/HUMAN_ESCALATION_POLICY_2026-10-06.md | Guard, authority, approvals, effects, verification | Unchanged; no skill-side approval |
| docs/KNOWLEDGE_LIFECYCLE_MANAGEMENT.md | Original owner/source/revision and derived knowledge | Unchanged; no second memory store |
| docs/SYSTEM_ROLE_BOUNDARIES.md and docs/GITHUB_AUTO_DEVELOPMENT.md | Existing development OS owns task/worktree/session | Unchanged; skill cannot create its own queue |

pyproject.toml uses pydantic-ai-slim 2.47.0; tests/test_auto_capability.py is the baseline agent registration test. A scoped main-branch code search found no existing SKILL.md or skill_registry in the current Agent; this is not a complete historical inventory.

## P1 — staged code

- src/ai_foundation/agent_skills.py implements a read-only catalog with compiled host SHA-256 pins, bounded UTF-8 frontmatter and size, symlink/dirfd protection, metadata summaries and on-demand body load.
- src/ai_foundation/auto_agent.py adds optional load_skill(name) to the existing Pydantic toolset; no existing tool registration or permissions are changed.
- scripts/operator_server.py binds the first-party catalog once from its release root. Missing or altered bundles disable only the optional skill feature and are logged by exception class.
- Three original, non-executable SKILL.md guides: evidence-brief, verified-artifact and development-handoff. They use only permissions already present in the host.
- tests/test_agent_skills.py covers pin and file change, symlinks, unknown name, YAML failures and three deterministic Agent -> skill -> preauthorized capability paths.

The implementation is an explicit *limited parser subset* of the Agent Skills format: required scalar name/description and optional scalar license/compatibility/allowed-tools. Nested metadata maps, YAML block strings, and arbitrary full YAML are not yet accepted. Unsupported forms fail closed; this is not a claim of full specification compliance. The official specification is https://agentskills.io/specification .

## P2 — test scope and actual limitations

Synthetic acceptance tests are designed for:
A. evidence-brief -> existing SEARCH with a public fixed-query fixture;
B. verified-artifact -> existing DATA json_summary with fixed JSON input;
C. development-handoff -> existing CODE inspect with a fixed host repository root.

Each path is meant to verify exactly one existing tool invocation and no authority expansion. Passing these tests does **not** establish successful live provider inference, search retrieval, actual artifact write/readback, deployment, performance advantage, a running local model, or production operation.

The necessary next gate is focused tests plus full current-head CI and an independent real host readback. Afterward, a live public task and baseline Agent A/B comparison are needed before P2 may be called accepted.

## Deferred P3/P4 — no premature framework growth

Skill candidate generation should consume only independently verified success receipts with exact source revisions and make a tested Draft PR candidate, not let chat automatically publish new permissions or self-activate. Multi-skill execution should re-use the present Pydantic Agent and Durable Work rather than introducing a new scheduler, queue, model router, decision AI, memory database, or MCP server.

No new paid provider, credential, model installation, model termination, Native signal, main merge, or user data export is introduced by this PR.

At documentation time: P0 ownership mapping and P1 code are staged; P2 synthetic tests written, CI and real-host E2E not yet independently accepted.


## P3/P4 implementation extension — 2026-11-10

Source: Draft PR #553. **Not deployed, not auto-activated**. This section supersedes the earlier "Deferred P3/P4" historical wording.

### P3: host-only evidence-bound candidate generation and Draft handoff

- Source ai_foundation/skill_learning.py implements generate_skill_candidate() using the EXISTING host-authorized AgentPort, propose_skill_from_verified_artifact() with existing TextArtifactResult(status=VERIFIED_COMPLETE) and independent fresh SHA-256/byte-length readback, and deliver_tested_skill_draft() for host-owned acceptance and optional Draft PR delivery.
- Public-source ID, immutable source revision and an explicitly public objective are supplied by the trusted host; raw artifact bytes are not added to the candidate or sent to the proposal model by this module.
- Model-generated procedural text is always **untrusted Draft content**. It does not install packages, write or activate a runtime skill, change Guard, register a capability, or update trusted bundled SHA-256 pins.
- The development-owner Draft publisher receives complete candidate bytes, exact digest, source-based fingerprint and path. The existing developer owner must stage under its Guard-scoped repository, independently read back, avoid duplicate fingerprints, and verify Draft PR identity. Nonempty publisher reply is evidence of a candidate being presented, NOT runtime acceptance or deployment.
- No added permanent queue, scheduler, SQL DB, approval tier, credentials, model loader, autonomous publisher, or model-visible tool.
- Source tests in tests/test_skill_learning.py: forged/uncertain artifact refusal, source drift, invalid provenance/path, tamper/digest checks, failure must prevent publication, one existing AgentPort call, no model call before verified readback.

### P4: reuse ONE sequential Agent loop

- ai_foundation/auto_agent.py allows up to **two distinct** host-pinned procedural references per Agent task. A repeated load returns an already-loaded marker without repeating the entire body. A third distinct Skill fails before lookup; the task-local load set resets between runs.
- No new model router, parallel inference, front-loaded semantic classifier, tool grant, workflow queue or scheduler. The existing Pydantic AI agent and exact host-scoped executor remain authoritative, and the original four-tool-call budget is unchanged.
- Fixed tests/test_agent_skills.py exercises two Skills followed by existing DATA CapabilityExecutor and zero Guard side effects. More complex long-running work must use existing reviewed durable contracts.

### Remaining real acceptance and rollout

- P2 real local-9B A/B and actual verified work artifact still unaccepted. Latest fixed M1 CI #42777529066 reported BLOCKED_CPU_PRESSURE, with #570 indicating insufficient free RAM for cold start. No bypass, forced model termination or paid fallback.
- P3/P4 source and tests are implementation at Draft stage, NOT claimed production automation. Real-source generation, real Draft handoff, actual daily multi-Skill workload, and independent source/output readback remain separate E2E gates.
- Feature default: AI_FOUNDATION_SKILLS_ENABLED=0. No main merge or live operator switch, Native signal, secret export, or paid model enrollment.
- Next: latest HEAD focused CI, full pre-integration regression, then genuinely public host-authorized daily task and readback. Do not mark integration complete based only on fixed fixtures.
