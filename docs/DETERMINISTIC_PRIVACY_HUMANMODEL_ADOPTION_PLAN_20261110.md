# AI-Foundation — 9B非依存の秘密値検出・HumanModel検索 導入計画
2026-11-10 / PLAN ONLY (no new binary, inference route, production rollout or main merge)

## 0. Decision and existing evidence

Goal: remove routine HumanModel maintenance, secret/PII prescreen, and exact historical decision lookup from the contested 9B compute queue. Preserve source ownership and Guard authority; only new semantic interpretation remains a model task.

Canonical existing code reviewed:
- `src/ai_foundation/guard.py`: `GuardCore.preflight` currently returns `LOCAL_ONLY` on label/keyword regex within `TaskPlan.privacy_text` (or text).
- `src/ai_foundation/inference_service.py`: `GuardedInferenceService.run` calls Guard then selects cloud/local; returns `LOCAL_RESOURCE_DEFERRED` on shared-compute contention.
- `src/ai_foundation/question_bridge.py`: another keyword route exists for questions; it is not the general outbound enforcement boundary and must not be treated as one.
- `src/ai_foundation/human_model_context.py`: owner-bound, Guard-approved, current view `read()` of at most 32 records / 32 KiB; `search()` currently delegates to optional Cognee.
- `src/ai_foundation/human_model_primary_review.py`: exact decision/Canon/Guard binding already non-LLM; never turn fuzzy matches into consent.
- `experiments/human_model/human_model_ledger.py`: HumanModel-owned SQLite originals, revisions, disputes, invalidation and approved-view projection.
- `src/ai_foundation/knowledge_lifecycle.py`: source ID/revision/hash, ownership, privacy and deterministic no-effect reconciliation.
- `src/ai_foundation/klm_drive_work.py`: KLM semantic handler runs under original shared HostComputeLease; `WAIT_DEV_IDLE` applies before model work.
- Separate contention fix: Draft PR #561; scheduling follow-up Issue #562. This plan does not modify leases, 9B concurrency or the KLM development-priority policy.

Research decisions from prior investigation: Betterleaks vs Gitleaks need exact pinned M1 A/B; detect-secrets remains comparison fallback; Presidio is optional only after Japanese PII gap measurement; SQLite FTS5 first, RapidFuzz optional candidate retrieval, Splink/TruffleHog/Secretlint out of initial build. Previous synthetic Guard regex / fuzzy micro-tests are preliminary; reproducible fixtures + exact-M1 receipts are still required.

## 1. Non-negotiable authority and privacy invariants

1. Scanner finding is **evidence of possible sensitivity**, never external-send permission. No finding is **not** proof of public/shareable. Provenance-based source privacy (private/restricted/shareable), destination grant, owner and scope take precedence.
2. Guard, Canon, LV1–LV5, HumanModel owner-approved view and CredentialBoundary remain the only existing authority sources. No new approval levels, personality inference authority, permission widening, private original copy to GitHub or fabricated owner choices.
3. Inspect the actual data about to cross each outbound inference boundary: user input, attachment content and selected tool/source results. Respect trusted origin metadata, not assistant/system text keyword matches alone. Missing source coverage, stale authorization or an incomplete scanner result => `LOCAL_ONLY` when feasible; otherwise `DEFER/UNAVAILABLE`. Never silently fail open or fall back to paid/cloud.
4. Raw secrets never enter argv, environment, scanner report files, telemetry, GitHub Issues, model logs, exceptions or external validation. Scanner consumes bounded bytes over stdin on the host. Only fixed reason codes and aggregate counters may be published.
5. Zero external network for scanning, including plugin updates, config fetching, credential validation, analysis or revocation. Require an OS-enforced network sandbox plus no-network synthetic acceptance, not only a CLI flag.
6. No new resident daemon, persistent duplicate personal-data database, new/forced local model, paid provider, main merge, deployment or Native signal without a separate approved release.
7. Scanner failure/timeout, malformed result, excessive input, unknown rule/config hash and unavailable tool are `UNKNOWN`, not `CLEAR`. Normalize only trusted records. Cache by source revision/content hash + detector version/config + owner/scope for bounded reuse; do not retain raw content.

## 2. Target minimal dataflow

```text
Authenticated source / user input / tool result
  -> trusted source metadata (owner, scope, revision, privacy, coverage)
  -> bounded deterministic detector (credential patterns, Japanese structured PII)
       + optional locally sandboxed Betterleaks/Gitleaks adapter
  -> privacy assessment (SENSITIVE / NO_FINDING / UNKNOWN; reason codes, no raw match)
  -> existing Guard + destination grant / Canon / CredentialBoundary
       -> shareable + complete + expressly permitted destination: eligible provider
       -> restricted/private/unknown: confined local path or explicit DEFER
  -> no scanner-generated execution/approval authority
```

**Where to connect**: shared host-side pre-send policy helper, invoked by all outbound provider adapters rather than only one chat front end. `GuardedInferenceService.run()` should consume already trusted provenance/scan result before routing. Audit Pydantic/AutoCapabilityAgent, selected tool-result assembly and other CloudInferencePort callers for bypass paths. Preserve `TaskPlan.privacy_text` user-origin semantics; introduce source-provenance metadata independently so assistant prose does not poison classification and private tool results are not omitted. Re-evaluate immediately before sending, not only at ingestion.

Proposed small modules (names subject to code audit):
- `src/ai_foundation/sensitive_input_scan.py`: pure bounded detector protocol, result/unknown reason codes, Japanese structured PII (email/phone/postcode and checksum where appropriate) and optional scanner adapter; no authority.
- `src/ai_foundation/inference_privacy_boundary.py`: source metadata + destination policy consumption through existing Guard/route contract; NO new global semantic classifier or independent approval service.
- `tests/test_sensitive_input_scan.py`, `tests/test_inference_privacy_boundary.py`: deterministic tests on synthetic-only material, local/cloud mock ports and tool responses.
Do not change `question_bridge.py` merely to enable a new Kandev route; reuse common detector only where the real host path needs it.

## 3. Betterleaks v Gitleaks adoption gate (no default choice before M1 evidence)

- Reconfirm exact upstream release tag, license, code tree, binary SHA/architecture and CLI help on the candidate **version** (upstream main documentation spans version-specific flags). Pin executable and rule configuration by digest. Do not install in production during evaluation.
- Test stdin-only, no network, no remote repository/URL source. Disable validation *and* analysis explicitly, clear corresponding inherited environment, and independently deny outbound traffic. Betterleaks may still export `match.value` in JSON; parse/redact entirely in-memory; publish only category/counter and fixed outcome.
- Same synthetic fixture set: common API keys, standalone/high-entropy tokens, multiline/private key, transforms, false-positive prose (JP/EN), malformed Unicode, empty/large inputs, sensitive nested tool results, scanner timeout/crash and network attempts. Include negative controls to measure false positives.
- Measure per-category TP/FN/FP, zero network requests, binary RSS/CPU/startup latency, total decision-path overhead with and without existing 9B workload. Identify which categories are only heuristic. No guessed 100% real-world recall.
- **Decision**: adopt exactly one scanner only if it demonstrably improves the existing baseline within measured M1 memory/latency budget and never degrades policy fail-closed behavior. Otherwise keep built-in rules, and retain OSS as optional CI security tool. Neither product is a trusted 'safe-to-send' oracle.

## 4. HumanModel deterministic search, WITHOUT new semantic authority

Existing `HumanModelContext.read()` remains the only authenticated source reader and privacy/Guard gate.
- Introduce a bounded in-memory SQLite FTS5 `trigram` index over the current **already approved complete** view; no persistent duplicate private index, no cloud search and no eager model call. Query is local, source IDs/revisions preserved.
- Short strings (<3 Unicode characters such as `9B`) and exact IDs use a bounded literal/ID path; `unicode61` alone is not sufficient for Japanese substring matching. Explicitly distinguish `NO_MATCH`, `PARTIAL`, `UNAVAILABLE` and `STALE`.
- Apply permitted-record canonical equality checks on retrieved rows as current Cognee path does. Invalidate on view revision/hash change, owner/scope change, supersession or dispute. Reject partial/unapproved views for a claim of complete search; never imply whole-ledger completeness from one 32-record page.
- RapidFuzz, if needed, operates only on already approved, bounded candidates for **review proposals**. Negation, numeral/date/amount changes, conflicting decisions or scope changes inhibit auto-merging. Similarity cannot resolve `HumanModelPrimaryReview` or create approval.
- Keep current Cognee search optional for real semantic exploration, but prefer deterministic retrieval for explicit IDs/keywords; no automatic model start. Preserve existing `human_model_context` and `human_model_search` tool signatures where possible.
Proposed module: `src/ai_foundation/human_model_search_index.py` with focused tests. A source-owner-side persistent FTS index is a later opt-in only if volume/latency evidence proves the bounded in-memory path inadequate.

## 5. KLM integration and actual 9B queue reduction

Perform now without 9B: source metadata sync, exact-revision/scope/privacy checks, hash/duplicate comparisons, stale view invalidation, deterministic relation candidates and original-bound no-effect audit. Record `NO_MODEL_REQUIRED`, `SEMANTIC_REVIEW_REQUIRED` or `SOURCE_UNCERTAIN` without claiming a meaning that was not inferred.

Only **new, unresolved semantic interpretation** enters the existing KLM 9B handler and shared lease. An approved development Issue is backlog, not compute occupancy; fair scheduling is separately owned by Issue #562, not stealthily changed by this privacy/HumanModel plan. Do not increase local concurrency, force-stop shared Ollama, switch to 4B or retry unknown effects.

## 6. Build stages and gates

### S0 — source audit + reproducible fixtures (no production changes)
- Inventory all ingress, agent, tool-result and provider egress paths; identify which have owner/scope/privacy metadata today.
- Freeze 100% synthetic fixture manifest with expected categories/coverage; record existing Guard false negatives and false positives.
- Check actual M1 environment (available RAM, no duplicate scanner daemon, Python sqlite FTS5 availability). No personal originals in test artifacts.
- Exit: reproducible source-only tests and complete path/coverage matrix; no unaccounted outbound path.

### S1 — OSS scanner benchmark in isolation (not yet an admission gate)
- Gitleaks and Betterleaks at pinned exact tags, network-denied stdin sandbox, shadow-only output and parser. Prefer no additional persistent tool if built-in detector sufficiently covers the real needed categories.
- Exit: identical fixture comparison, zero egress, crash/timeout safe outcomes, measured M1 cost, binary/license/provenance receipt and explicit selection/rejection rationale.

### S2 — host metadata and pre-send hard gate
- Add minimal pure `PrivacyAssessment`, source metadata coverage and single egress policy; run shadow classification, then gate under existing Guard only after tests.
- Exit: in real and synthetic paths, no private/unknown tool/user/attachment bytes reach cloud; old permitted public flow is not unnecessarily blocked; no paid fallback; denial emits redacted reason codes; rollback switch restores *previous policy without allowing leaks*.
- Preserve model-independent deterministic execution when no eligible model.

### S3 — HumanModel deterministic search
- Add bounded FTS5 against complete Guard-approved read snapshots, short-query fallback, optional RapidFuzz proposal-only ranker, current-revision validation and audit receipt.
- Exit: real approved source returns exact original IDs with no model call; foreign/stale/partial/disputed view cannot be promoted; short JP query, negation, changed amount/date and correction fixtures pass; no duplicate private persistent DB.

### S4 — KLM inference pruning and accepted routing
- Classify only no-effect/exact operations as `NO_MODEL_REQUIRED`. Keep semantic ambiguity queued for the accepted 9B/LOCAL_ONLY route. Coordinate contention measurements with #562 without altering its release.
- Exit: before/after 9B calls and waiting jobs measured on the same synthetic work queue; correctness and source privacy unchanged; unknown work remains pending.

### S5 — optional Japanese PII expansion (only with measured gap)
- Start with standard library + `phonenumbers`/checksum validators when proven useful; only then evaluate Presidio with rule-only setup, and separately GiNZA when name/address recall requires non-generative NER.
- Exit: tangible precision/recall gain on realistic *synthetic* Japanese cases, reviewed model/license/dependency, observed M1 RSS and no 9B pressure. Otherwise exclude without adding a resident service.

## 7. Final acceptance and reporting

Separate synthetic CI, isolated physical M1 observation, owner/privacy policy review and safe release; do not infer E2E from an OSS benchmark or unit tests. Record: each scanner version/digest, config digest, mock source/expected output counts, zero external calls, duration/RSS, false negatives/positives by category, HumanModel source-ID validity, blocked cloud attempts, 9B call count/wait/backlog before and after. Never output raw credentials or personal content. Prefer concise status deltas to perpetual notification.

End-state expected:
- secret detection and source-privacy routing do not need 9B;
- HumanModel exact/current retrieval, provenance, invalidation and primary delegation review do not need 9B;
- 9B is reserved for meaning not determined by trusted source records;
- any unknown or conflicting private/authority item is deferred, not guessed, silently cloud-routed or auto-authorized.

## Upstream specs consulted
- https://github.com/betterleaks/betterleaks/blob/main/docs/scanning.md (current main; **verify pinned tag** before choosing flags; explicit validation/analyze can transmit)
- https://github.com/betterleaks/betterleaks/blob/main/docs/config.md
- https://www.sqlite.org/fts5.html (trigram requires 3-character tokens for full-text matching)
- https://rapidfuzz.github.io/RapidFuzz/Installation.html (macOS wheels)
- https://microsoft.github.io/presidio/analyzer/ (configurable PII recognizers / NLP)


## 8. Codex OSS harness reuse check (2026-11-10 addendum)

Source: https://github.com/openai/codex (Apache-2.0);
official descriptions:
- https://developers.openai.com/blog/codex-as-a-platform
- https://learn.chatgpt.com/docs/agent-approvals-security
- https://github.com/ollama/ollama/blob/main/docs/integrations/codex.mdx

**Separate engine from model.** Codex open-sources the agent harness, macOS Seatbelt command sandbox, CLI, SDK, app-server, execution/approval policy and local Ollama adapter. Codex does *not* provide deterministic secret/PII detection, private HumanModel evidence classification, or an alternative to FTS5. `codex exec`, SDK agent run and app-server conversation require a model; `codex --oss` can run on Ollama but consumes the same contested local 9B model/host memory. Do not confuse Apache-licensed code availability with free model/API entitlement.

### Where Codex could be reused without competing for 9B

- **S1 optional tool containment**: `codex sandbox macos [COMMAND]...` is documented as a standalone command to run a tool under macOS Seatbelt. Evaluate it *without invoking `codex exec`* as a runner for the Betterleaks/Gitleaks comparison, alongside the already present `/usr/bin/sandbox-exec` fixed Seatbelt setup in `scripts/local9b_task_recipe.py` and `experiments/human_model/cognee_bridge.py`. Before treating Codex as a substitute, prove it takes no model token, does not demand authentication/network, denies egress and out-of-scope reads/writes, confines stdout/stderr containing synthetic findings, and has acceptable M1 RSS/start latency. If no material advantage over existing sandbox, **do not add Codex dependency**.
- **Self-development only (separate workstream)**: `codex exec` and SDK/app-server could be a bounded future executor for eligible public/source-sanitized coding tasks under existing Foundation Harness, development task/Guard/Canon and existing budget/privacy authority. Its value is tool-driven code editing, test invocation and structured feedback, not regex scanning or automatic HumanModel personalization. Never introduce a second scheduler, approval hierarchy or PR writer. Any ChatGPT subscription route is an independently verified existing-entitlement route, *not* a free API key; no automatic metered fallback. `--oss -m <local model>` requires explicit model selection and acceptance of context/tool compatibility, and does not create extra 9B throughput.
- **Reference-only**: Codex Rust exec-policy, approvals, sandbox and patch-source can inform tests but directly copying crates into Foundation duplicates Cedar/Guard/Pydantic AI/Hatchet/ToolHive and creates upstream version burden. Prefer officially exposed CLI/SDK with a narrowly scoped contract if practical.

### Codex acceptance extension (S1, no production change)

1. Inspect whether an official Codex binary is *already installed* on the M1; no download or install if absent during source-only planning. Historical workflow names in `docs/evidence/issue222/workflow-inventory.md` do not establish current Codex availability.
2. Against a disposable synthetic fixture run the **same** scanner command (not Codex agent) in Codex sandbox and the current Seatbelt runner, keeping scanner configuration pinned.
3. Verify both deny outbound requests, privileged filesystem access, and write outside exact temporary workspace; check no model calls, file exposure or persistent auth/telemetry.
4. Compare execution overhead, compatibility, observability, version pinning and maintenance surface; if existing Seatbelt meets identical invariants, mark Codex sandbox `NOT_ADOPTED_DUPLICATE`.
5. Keep any future Codex agent capacity experiment outside this privacy/HumanModel rollout, tracking separately under existing #562 free remote-Harness work.

This addendum is not an endorsement of running actual secret values through Codex agent prompts or sharing restricted HumanModel source views with an external Codex service.


## 9. Existing DeepSeek Harness is the parent; official Codex/Claude subagents already exist (2026-11-10 correction)

**Current Foundation reality**: `scripts/local9b_autodev_worker.py` already calls private, pinned DeepSeek Harness `dsh --profile headless` through `HarnessProposalAgent` in `src/ai_foundation/development_host.py`, with host-owned Seatbelt, dedicated qwen3.5:9b Ollama and 9B compute lease. `docs/M1_BRIDGE_RUNTIME_STATUS_20261107.md` explicitly states DSH is on-demand CLI, not a required resident web port. `docs/evidence/development_loop/REAL_9B_DRAFT_20261107.json` proves actual 9B->source->fixed test->Draft PR #249 with **manual host resume**, not fully unattended production E2E. This production-source path is NOT merely a proposed unused harness. Supersedes any implication in section 8 that Foundation does not already own/use DSH.

**DeepSeek upstream already provides the requested composition**:
- https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/subagent/subagent-codex/README.md — optional `@deepseek-ai/dsh-subagent-codex` Profile Bundle; real official Codex app-server one-shot child, native Codex auth/model/approval/sandbox; no model switch/remote grant by itself. Parent owns child status/results but subprocess consumes a *separate* model quota/context. Host `subagent_codex` tool registers on demand; one-shot, no resume or pooling. No built-in human approval handoff, wall-clock timeout or side-effect rollback, so it must not inherit Foundation production write authority.
- https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/subagent/subagent-claude-code/README.md — analogous official Claude Code child via Agent SDK.
- https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/subagent/README.md — unified subagent registry/ownership; existing subagent provider is preferable to a custom DSH-to-Codex orchestrator.
- https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/providers.md — Anthropic/Claude can also be a **model provider** inside DSH, which is distinct from running full Claude Code as a subagent.

**Correct shape**:
```text
Foundation / Canon / existing Guard / task owner / HostComputeLease
  -> existing DeepSeek Harness (selected pinned headless profile)
       -> 9B proposal-only model OR separately approved model-provider route
       -> optional official Codex or Claude Code child for bounded independent coding only
  -> existing Foundation fixed tests / Guard writes / source & PR readback
```

**For *this* privacy/HumanModel project**: prefer no agent at all on the hot path. Run Betterleaks/Gitleaks directly under the existing Seatbelt; use SQLite FTS5 + optional RapidFuzz for source read/search. Codex/Claude subagents cannot replace deterministic detection; introducing them there increases dependencies and model usage. In S1 evaluate Codex's standalone sandbox only if the existing sandbox proves a concrete missing capability.

**If/when testing Codex as an optional child**, separate exploratory acceptance from production:
1. Inspect exact installed DSH version, current pinned private profile and whether `dsh-subagent-codex` exists/enabled. **Never alter current production headless 9B profile or credentials during discovery**. Upstream availability is not installed availability.
2. In a disposable profile/repository with fixed public tasks, verify subagent startup, one-shot result, no unapproved writes, no shared-secret / private HumanModel prompts, scoped filesystem/exec permissions, cancellation and no automatic commit/push/merge.
3. Prove provider is a permitted existing-entitlement/free route with **automatic metered billing impossible**. A Claude/ Codex model setting or upstream native authentication is not permission to spend.
4. Ensure one Canon/Guard owner for effects. Native child approvals denied on unknown requests; host is responsible for actual approved output/readback. No duplicate task scheduler, no independent task ledger and no parallel model execution on the same 16GiB M1 unless physically accepted.
5. Measure aggregate utilization: a 9B parent waiting on cloud child may still own a live lease and 9B context; configure schedule/delegation intentionally. Do not infer reduced 9B contention simply from adding a child. Match #562's resource scheduler.
6. If Codex native child does not add verified task quality/capacity over existing DSH provider + Foundation fixed host workflow, record NOT_ADOPTED_DUPLICATE.

This supersedes the naive idea of wrapping Codex inside a freshly built Foundation harness. Existing DSH + its upstream optional subagent is the only eligible Codex-agent experiment path. No new OSS, plugin, account or daemon has been installed in this documentation change.

## 10. HumanModel management is a prerequisite distinct from retrieval (2026-11-10)

Source audit found that search, evidence history and View invalidation exist, but **end-to-end management** (authenticated actor and consent → source-bound intake → correction/retraction → invalidation → current View publication → audit/recovery/erasure) is not yet accepted. In particular, current `Ledger.rebuild_view` includes un-superseded `kind='inference'` and `disputed` evidence without a personal-approval filter, and a `decision_events` string `actor='user'` is not host identity proof. Search-result membership and lexical similarity must not be promoted into accepted user judgments or Guard approval.

Canonical management contract: `docs/HUMANMODEL_LIFECYCLE_MANAGEMENT_CONTRACT_20261110.md`, Draft PR #607, Issue #606. It inventories 26 distinct responsibilities, existing capabilities and missing gates. P0 is a read-only no-model ledger/View structural audit with synthetic fixtures; it reports status/counts only, not personal text or source IDs. **`STRUCTURE_OK_SOURCE_UNVERIFIED` does not attest owner/source or consent**. Follow-up P1–P5 cover authenticated source/actor/consent, version-bound owner writer, derived invalidation, deterministic search, maintenance, backup and erasure.

**Update to S3**: FTS5/RapidFuzz remains a retrieval optimization, not a substitute for lifecycle management. Enable it only against current, bounded, Guard-approved source Views and never interpret a selected `inference` or `disputed` record as a fixed personal fact. Do not use FTS5 or Codex/DeepSeek Harness to decide user consent or grant. Source admission/meaning claims must independently pass the management owner and Guard gates.
