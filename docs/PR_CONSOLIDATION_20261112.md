# Consolidated disposition of 52 former open PRs (2026-11-12)

**Source of reconciliation:** main `5a72be02bf5d32a2f3340ac59e3582019f93127d`. The table below pins original PR HEADs before closure; the original commits and patches remain available from GitHub even after the PRs close. No branch is deleted.

**Decision:** Carry only absent, independent, opt-in source modules and their focused tests from eight source PRs. Do not replace main's later `Guard`, Operator, 9B worker, provider policies, current HumanModel, or production workflows. Source inclusion is not live acceptance or permission to run.

**No effect:** zero model/provider calls, no payment route, no installed service change, no Issue #35 Native dispatch, no automatic Drive/private-data ingestion, no change to main until independent PR merge.

## Adopted exact source blobs

| Original PR | Source-only files added |
|---|---|
| [#6](https://github.com/quest7070-dev/AI-Foundation/pull/6) | `src/ai_foundation/job_notification_policy.py`, `tests/test_job_notification_policy.py` |
| [#55](https://github.com/quest7070-dev/AI-Foundation/pull/55) | `src/ai_foundation/external_research_handoff.py`, `tests/test_external_research_handoff.py` |
| [#80](https://github.com/quest7070-dev/AI-Foundation/pull/80) | `experiments/human_model/companion_review_benchmark.py` |
| [#145](https://github.com/quest7070-dev/AI-Foundation/pull/145) | `src/ai_foundation/muse_delivery_state.py` |
| [#236](https://github.com/quest7070-dev/AI-Foundation/pull/236) | `experiments/m1_host_admission/proposal.py`, `experiments/m1_host_admission/bound_evidence.py`, `tests/test_issue223_admission_proposal.py`, `tests/test_issue223_bound_evidence.py` |
| [#256](https://github.com/quest7070-dev/AI-Foundation/pull/256) | `scripts/local9b_gguf_header.py` |
| [#478](https://github.com/quest7070-dev/AI-Foundation/pull/478) | `scripts/groq_models_readonly_preflight.py`, `tests/test_groq_models_readonly_preflight.py` |
| [#607](https://github.com/quest7070-dev/AI-Foundation/pull/607) | `src/ai_foundation/human_model_literal_search.py` |

Original PR titles were damaged by a previous export and are now omitted rather than misquoted. Open the linked original PR for its actual title. Source SHA presence or blob equivalence is **not** a complete semantic reconciliation of all functionality.

## All original 52 PRs and disposition

| PR | Original HEAD | Disposition |
|---|---|---|
| [#607](https://github.com/quest7070-dev/AI-Foundation/pull/607) | `518d11447304b4df00686e8c0f6504562f46f6a6` | `PORT_SOURCE_ONLY` |
| [#481](https://github.com/quest7070-dev/AI-Foundation/pull/481) | `2875a8c8b0cf68c570a2e8c759084f421a4eafee` | `SUPERSEDED_BY_MAIN` |
| [#478](https://github.com/quest7070-dev/AI-Foundation/pull/478) | `eba1f8c73cc986c2fbb91db110ab6d8b232d218a` | `PORT_SOURCE_ONLY` |
| [#470](https://github.com/quest7070-dev/AI-Foundation/pull/470) | `6f6a6d448e222e359e8122a4c38410247ff41a79` | `SUPERSEDED_BY_MAIN` |
| [#256](https://github.com/quest7070-dev/AI-Foundation/pull/256) | `fd5abad953d99efba6369b961e3b7e1163752142` | `PORT_SOURCE_ONLY` |
| [#248](https://github.com/quest7070-dev/AI-Foundation/pull/248) | `eeb584a2d488de94c25c1836a36c0328e61bca0f` | `SUPERSEDED_BY_MAIN` |
| [#242](https://github.com/quest7070-dev/AI-Foundation/pull/242) | `441d1c23dfeb59e18c401ae4e3777c5ab413642a` | `EXPERIMENT_REQUIRES_SEPARATE_ACCEPTANCE` |
| [#236](https://github.com/quest7070-dev/AI-Foundation/pull/236) | `a6e83a7b7be96a5e7af54b77a04998ebf122251e` | `PORT_SOURCE_ONLY` |
| [#225](https://github.com/quest7070-dev/AI-Foundation/pull/225) | `438c27a2f25a5c3d7ecc33f0ab0581c6a76c547f` | `ISOLATED_PASEO_NATIVE` |
| [#224](https://github.com/quest7070-dev/AI-Foundation/pull/224) | `8c0ff1525e548e397e0441cd4a8c6db9d17705c7` | `ISOLATED_PASEO_NATIVE` |
| [#213](https://github.com/quest7070-dev/AI-Foundation/pull/213) | `6aaf853f3da4162a2eefd7465cdaa6740f191a8c` | `ISOLATED_PASEO_NATIVE` |
| [#210](https://github.com/quest7070-dev/AI-Foundation/pull/210) | `f23a85b498e589b4f50608e62af915fb8e2e0a23` | `ISOLATED_PASEO_NATIVE` |
| [#207](https://github.com/quest7070-dev/AI-Foundation/pull/207) | `e2b110fdc118f389f345117f16fac2760774dc65` | `ISOLATED_PASEO_NATIVE` |
| [#204](https://github.com/quest7070-dev/AI-Foundation/pull/204) | `e2f6a796b45231a746c07708e2b67e5785b5aa7f` | `SUPERSEDED_BY_MAIN` |
| [#202](https://github.com/quest7070-dev/AI-Foundation/pull/202) | `c564f0c6111922a1172c1baae26c822f8a58f5a3` | `EXPERIMENT_REQUIRES_SEPARATE_ACCEPTANCE` |
| [#201](https://github.com/quest7070-dev/AI-Foundation/pull/201) | `17adedf566086cfb99a535d2e974eaf4161e2801` | `SUPERSEDED_BY_MAIN` |
| [#199](https://github.com/quest7070-dev/AI-Foundation/pull/199) | `d10c9653932945e41eeafd0f1f27b6b43a559b4f` | `SUPERSEDED_BY_MAIN` |
| [#194](https://github.com/quest7070-dev/AI-Foundation/pull/194) | `e0af221d4ee2b6b5ea6f0953d48815704311d774` | `ISOLATED_PASEO_NATIVE` |
| [#184](https://github.com/quest7070-dev/AI-Foundation/pull/184) | `03684d4d481552e8721eee76c11cc134ab7146e3` | `ISOLATED_PASEO_NATIVE` |
| [#178](https://github.com/quest7070-dev/AI-Foundation/pull/178) | `cb68caae040e93f3ec36bc2308929fd57403b6d4` | `ISOLATED_PASEO_NATIVE` |
| [#177](https://github.com/quest7070-dev/AI-Foundation/pull/177) | `40eca01bb4047b03be8242cd52dc3e4e364cd5ef` | `EXPERIMENT_REQUIRES_SEPARATE_ACCEPTANCE` |
| [#175](https://github.com/quest7070-dev/AI-Foundation/pull/175) | `561ad148b01b055071ac1dc5ea777c1e2430c501` | `ISOLATED_PASEO_NATIVE` |
| [#174](https://github.com/quest7070-dev/AI-Foundation/pull/174) | `c930ab5613f63064054df1c9ad625a98fdd695bc` | `ISOLATED_PASEO_NATIVE` |
| [#173](https://github.com/quest7070-dev/AI-Foundation/pull/173) | `d94922de07688a52993776120c4c1c07f8a623b7` | `ISOLATED_PASEO_NATIVE` |
| [#172](https://github.com/quest7070-dev/AI-Foundation/pull/172) | `b4691c1f6bfe51518e98ead9c5fb0d1098211a84` | `ISOLATED_PASEO_NATIVE` |
| [#171](https://github.com/quest7070-dev/AI-Foundation/pull/171) | `bd8f5b56ab4a1c6ae2c519b651f6fd166113cb48` | `ISOLATED_PASEO_NATIVE` |
| [#167](https://github.com/quest7070-dev/AI-Foundation/pull/167) | `cfe0873da4fb37018e08bc1d51d0fce569ea1ce6` | `ISOLATED_PASEO_NATIVE` |
| [#166](https://github.com/quest7070-dev/AI-Foundation/pull/166) | `c6bbe597d950c9539ee07bf7e8726fbe6c4a4ad9` | `EXPERIMENT_REQUIRES_SEPARATE_ACCEPTANCE` |
| [#165](https://github.com/quest7070-dev/AI-Foundation/pull/165) | `8531228f923df601b4f848923b1ad1e20296c451` | `ISOLATED_PASEO_NATIVE` |
| [#164](https://github.com/quest7070-dev/AI-Foundation/pull/164) | `61a5e9feb6596c825beba19f34050fbdb0dc46c0` | `ISOLATED_PASEO_NATIVE` |
| [#163](https://github.com/quest7070-dev/AI-Foundation/pull/163) | `ee78f5c10ab3770b9d8edde4457e0b525d95da61` | `ISOLATED_PASEO_NATIVE` |
| [#149](https://github.com/quest7070-dev/AI-Foundation/pull/149) | `8d9a5a1f2f0f31aa3387f192ea19a0f4e5c648ab` | `EXPERIMENT_REQUIRES_SEPARATE_ACCEPTANCE` |
| [#145](https://github.com/quest7070-dev/AI-Foundation/pull/145) | `de22940f68192036dfae71ec29069422a12cdb39` | `PORT_SOURCE_ONLY` |
| [#126](https://github.com/quest7070-dev/AI-Foundation/pull/126) | `019a3383899458c2166265fba5600c7e5f3861e5` | `ISOLATED_PASEO_NATIVE` |
| [#124](https://github.com/quest7070-dev/AI-Foundation/pull/124) | `4eff8b240d016375e86e1c06891278b4c4dd2f7c` | `ISOLATED_PASEO_NATIVE` |
| [#123](https://github.com/quest7070-dev/AI-Foundation/pull/123) | `9a8c5b73d20a9ffc559fbc5b23dd4f108a0470ef` | `ISOLATED_PASEO_NATIVE` |
| [#122](https://github.com/quest7070-dev/AI-Foundation/pull/122) | `75a62214ca492d4ee4b0a2d80425b42b7ae78a98` | `ISOLATED_PASEO_NATIVE` |
| [#121](https://github.com/quest7070-dev/AI-Foundation/pull/121) | `bc097b57ebde228efbdb78d32ab8bc0f6abc6489` | `ISOLATED_PASEO_NATIVE` |
| [#120](https://github.com/quest7070-dev/AI-Foundation/pull/120) | `86128697b98172fea9d014e80d6f2001ae61ba56` | `ISOLATED_PASEO_NATIVE` |
| [#119](https://github.com/quest7070-dev/AI-Foundation/pull/119) | `d63317b7ae55f90178f38c0107771eefe440e837` | `ISOLATED_PASEO_NATIVE` |
| [#117](https://github.com/quest7070-dev/AI-Foundation/pull/117) | `c365e1c215fbcd3e5c440ce2d0d13565412c0d57` | `ISOLATED_PASEO_NATIVE` |
| [#115](https://github.com/quest7070-dev/AI-Foundation/pull/115) | `12bb3f71bf6a3431bea5b0e413eb6aa357d6e1e3` | `ISOLATED_PASEO_NATIVE` |
| [#109](https://github.com/quest7070-dev/AI-Foundation/pull/109) | `6685b4b8e792af3ef0c3182f1dc57887c5ecbdba` | `ISOLATED_PASEO_NATIVE` |
| [#81](https://github.com/quest7070-dev/AI-Foundation/pull/81) | `009d73b25f6c99d34734db4c96791a6d61731ecc` | `EXPERIMENT_REQUIRES_SEPARATE_ACCEPTANCE` |
| [#80](https://github.com/quest7070-dev/AI-Foundation/pull/80) | `963522b0a861645f5625849cb5595996be9e14b3` | `PORT_SOURCE_ONLY` |
| [#55](https://github.com/quest7070-dev/AI-Foundation/pull/55) | `22183224e5c2d4304d2ddd1fbc3a67adb1c996ab` | `PORT_SOURCE_ONLY` |
| [#23](https://github.com/quest7070-dev/AI-Foundation/pull/23) | `b1c547bcc2ae316f9b2e8bc73b516a0f75234a9f` | `SUPERSEDED_BY_MAIN` |
| [#18](https://github.com/quest7070-dev/AI-Foundation/pull/18) | `31fbd5ad3c783f08de28a206742e65c5a5812676` | `SUPERSEDED_BY_MAIN` |
| [#8](https://github.com/quest7070-dev/AI-Foundation/pull/8) | `b3310c2b87dd615d914d8ac6a428449ec1fc1e9f` | `ISOLATED_PASEO_NATIVE` |
| [#6](https://github.com/quest7070-dev/AI-Foundation/pull/6) | `ac3b04401fc54013eaae7947cf776a4caa7f7a6b` | `PORT_SOURCE_ONLY` |
| [#5](https://github.com/quest7070-dev/AI-Foundation/pull/5) | `25a846a92ddff0742b05c511d6b4a0ec76e21a34` | `SUPERSEDED_BY_MAIN` |
| [#1](https://github.com/quest7070-dev/AI-Foundation/pull/1) | `98e5fb46208a72117e3a7353abd6f322b1c98ac3` | `SUPERSEDED_BY_MAIN` |

## Reasons and retained limitations

- **PORT_SOURCE_ONLY (8)**: A missing, inert/opt-in source primitive is carried in this consolidation. No deployment or existing runtime path changed.
- **SUPERSEDED_BY_MAIN (10)**: Main now has newer/independently implemented functionality, or the former branch is historical; do not overwrite newer tracked files.
- **ISOLATED_PASEO_NATIVE (28)**: Legacy stacked Paseo/Issue #35 Native/Guard path is isolated, not a validated main runtime dependency. Preserve exact source ref; prohibit automatic cutover/replay.
- **EXPERIMENT_REQUIRES_SEPARATE_ACCEPTANCE (6)**: Research/host/private-source branch lacks acceptance for present runtime, or is no longer the chosen model/service route. Preserve exact ref only.

All **52** old PRs are individually represented above. An original PR being closed is not a claim its entire change set is merged. For previously stacked or high-risk sources, the original head remains the immutable review location; reintroduction requires a new review against current main.

## Minimal acceptance

Run one exact-head Foundation CI on this one aggregate PR. Focused tests are imported only for source modules. If the source cannot pass current-main CI without broad changes, keep the aggregate PR open and fix only the focused incompatibility rather than rolling back main or reactivating legacy entrypoints.


## Post-consolidation targeted code reconciliation (2026-11-12)

This is an **incremental, reproducible source comparison**, not a claim of
complete function-level equivalence or a runtime cutover. Review baseline:
main `8d836ff9c03db1b2e047119443840b3b3a7a1314` (includes
[Canon/HumanModel repair #743](https://github.com/quest7070-dev/AI-Foundation/pull/743)
and [model-free CI lease fix #744](https://github.com/quest7070-dev/AI-Foundation/pull/744)).
All 52 recorded original PRs had their paginated changed-filename inventories
retrieved. The original #8 alone has 994 changed paths; filename presence and
similar symbol names cannot establish semantic feature preservation.

**Byte-identical originals now on main (selected higher-risk areas):**

| Original frozen PR HEAD | Confirmed exact matching source blobs on this main |
| --- | --- |
| [#607](https://github.com/quest7070-dev/AI-Foundation/pull/607) `518d11447304b4df00686e8c0f6504562f46f6a6` | `experiments/human_model/foundation_readonly.py`, `experiments/human_model/human_model_owner_publication.py`, `experiments/human_model/human_model_host_mcp.py`, `src/ai_foundation/human_model_collection_guard.py` |
| [#481](https://github.com/quest7070-dev/AI-Foundation/pull/481) `2875a8c8b0cf68c570a2e8c759084f421a4eafee` | `src/ai_foundation/development_admission.py`, `development_drive_plan.py`, `development_guard_admission.py`, `development_candidate_registry.py`, `scripts/local9b_positive_improvement.py`, `scripts/local9b_standing_admission.py` |
| [#478](https://github.com/quest7070-dev/AI-Foundation/pull/478) `eba1f8c73cc986c2fbb91db110ab6d8b232d218a` | `src/ai_foundation/free_route_admission.py`, `groq_staged_adoption.py`, `external_service_inventory.py` |

For each row, paths without a repeated `src/ai_foundation/` prefix refer to that
same directory. These observations were made by reading the original frozen
HEAD and current main through GitHub and comparing **blob SHA**, not by
assuming an old PR was merged.

**Nonidentical tracked source requires behavioral reconciliation, not copying:**
#607's `human_model_ledger.py`, `human_model_context.py`, `mcp_host.py`,
`human_model_ledger_verify.py`, `klm_drive_host_tick.py`; #478's
`harness_provider_adapter.py`, `development_host.py`,
`dev_autonomy_intake.py`. A preliminary Python symbol-name comparison found
no obvious missing *top-level* declarations in the first group and mostly new
declarations on main; that check cannot establish semantic equivalence.
The removed #478 `plan_with_local_ollama` planner must not be resurrected
merely because it is absent: deterministic/Harness intake superseded the
older local-4B-oriented path.

**Unported but not automatically authorized:** #145's Muse effect/notice
modules and #81's HumanModel Raw Inbox are not evidence of accepted present
runtime authority. Preserve their frozen heads and assess per-feature source
ownership, consent, dependencies and release effects before any opt-in port.
#8's old Paseo/Native stack is intentionally not a default execution owner.
Nothing in this audit opens a PR, issues an approval, ingests private content,
runs a model, or switches installed services.

**Separate work remaining:**

1. Compare each nonidentical function/behavior in all 52 original frozen HEADs
   against the later implementation and tests on current main; record explicit
   `PRESERVED`, `SUPERSEDED_WITH_EVIDENCE`, `MISSING`, or `UNRESOLVED`
   per feature. The existing category labels are not those proofs.
2. Carry a confirmed absent, still-desired safe function through **one**
   narrowly scoped recovery PR without replaying legacy installers or replacing
   newer Guard/Operator/HumanModel paths.
3. Reconnect newly discovered tasks through existing Foundation/Guard/Harness,
   without treating a diagnostic Issue as authorization. The existing finite
   standing-main-regression publisher supports only three predelegated
   source/test pairs; arbitrary CI failures are diagnostic. Consumed post-model
   attempts need a new reviewed scope, not a blind retry.
4. Preserve the HumanModel life-cycle goal in
   `docs/HUMANMODEL_LIFECYCLE_MANAGEMENT_CONTRACT_20261110.md`: original vs
   hypothesis, temporal change, contradiction, multiple purpose-bound views,
   owner proof and Concept OS separation. A successful 32-record retrieval or
   structural audit does not prove that goal has been achieved in production.

CI repair #744 removed the shared 9B lease from **model-free pytest only**;
its PR CI passed. Dedicated real-M1 inference acceptance still holds the
lease. Production installed revision, simultaneous live CI/9B behavior,
unrestricted autonomous development and all-52 semantic equivalence remain
**unverified**, and must not be reported as completed by this document.


## Frozen-HEAD semantic repair: #607 and #478 (2026-11-12)

This is **bounded function-level reconciliation**, not equivalence certification
for all 52 PRs. Original #607 HEAD:
`518d11447304b4df00686e8c0f6504562f46f6a6`; original #478 HEAD:
`eba1f8c73cc986c2fbb91db110ab6d8b232d218a`.
Compared actual frozen source function bodies with main, rather than interpreting
a missing file or newer timestamp as proof.

| Original function | Finding against main | Disposition |
| --- | --- | --- |
| #607 `human_model_ledger.Ledger.rebuild_view` | Same executable projection and excluded withdrawn/stale admission logic; comment wording differs | `PRESERVED` |
| #607 `human_model_ledger_verify.verify` | Same read-only integrity/management audit logic | `PRESERVED` |
| #607 `klm_drive_host_tick.owner_management_readonly_audit` | Existing audit retained; main additionally rejects non-false `execution_authority` | `PRESERVED/HARDENED` |
| #607 `human_model_context.read` | Guard-scoped snapshot retained, with main's added revision-bound sequential pagination and invalid-cursor rejection | `SUPERSEDED_WITH_EVIDENCE` |
| #607 `human_model_context.search` | Main's bounded literal search no longer re-read the current View before returning a match; this lost an old stale-source rejection | `RECOVERED_IN_THIS_REPAIR` |
| #607 `build_human_model_context` | Main had dropped the optional exact `GuardCollectionConsent` host binding needed to pass live consent verification into the existing owner-side View reader | `RECOVERED_IN_THIS_REPAIR` |
| #478 `dev_autonomy_intake.publish_ci_failure_task_drafts` | Main adds same-branch thread coalescing, guarded update, preserved prior-run links and continued unapproved status, rather than the old per-failure Issue creation | `SUPERSEDED_WITH_EVIDENCE` |

The repair restores **only** the optional existing host-owned
`collection_consent` read callback with exact owner/binding/Guard identity
checks, and a post-search same-revision/same-snapshot/Guard re-read for
literal and optional semantic results. It does not mint consent, enable
automatic collection, alter old legacy reads, run an LLM or change the
installed owner host. Tests use synthetic views and an inert reader.

**Still unresolved:** every other non-identical behavior in #607/#478 and
the other original PRs needs separately grounded review; these seven
function-level dispositions must not be extrapolated to all 52.
The live server still needs a **trusted authenticated host** to opt into
`collection_consent`; this source-level reconnection does not assert an
end-to-end real-owner consent or live deployment.

## Verified subsequent main integrations and bounded function dispositions (2026-11-12)

The 52 pinned original HEADs above remain the immutable audit set. The
following are **later, narrow repairs** confirmed as merged into main, not a
claim that closing the 52 original PRs merged all their functions.

| Repair PR | Accepted source-level effect | Merged commit |
| --- | --- | --- |
| [#750](https://github.com/quest7070-dev/AI-Foundation/pull/750) | Owner-answer complete bounded multi-page read with per-page identity/freshness checks (superseded by more scalable #755 selection) | `e70711299a0f3098f09ec38572737e3bf20027f3` |
| [#752](https://github.com/quest7070-dev/AI-Foundation/pull/752) | Restore #607 current-Guard consent read binding and pre-return literal/semantic source revision check | `6defc08fe43ab935db565e9ddb7d398db52360f7` |
| [#753](https://github.com/quest7070-dev/AI-Foundation/pull/753) | Existing 9B worker discovers only the three predelegated main regression pairs; no general execution authority | `a9a6ca63f2bb67878e78514dc7f2e24fbcda68c2` |
| [#754](https://github.com/quest7070-dev/AI-Foundation/pull/754) | Recover #478 Operator read-only provider/Harness service endpoints | `5ae22956a9fff960163c38f148af99fe7801aefd` |
| [#755](https://github.com/quest7070-dev/AI-Foundation/pull/755) | Owner-question reconstruction across paged evidence and scoped opt-in MCP; no default private-data exposure | `bd8ee00ff317e5c2510b11a38da481808d4f2fc7` |
| [#756](https://github.com/quest7070-dev/AI-Foundation/pull/756) | Restore #478 Infigraph symbol IDs with embedded pipe delimiters and redacted diagnostics | `51e667a5482007c6b00cd5767268eb7b7a403dda` |

**Further frozen #478 function-level comparison:** In
`src/ai_foundation/harness_provider_adapter.py`, five top-level function/class
bodies are exact matches: `compiled_source`,
`GroqHarnessIPv4Transport`, `_LocalHarnessExecution`,
`_HarnessServiceRouter` and `HarnessManagedProposalAgent`.
`default_harness_services` and `create_harness_managed_agent`
preserve Groq/local/Guard behavior while adding optional reviewed OpenCode
routing (`SUPERSEDED_WITH_EVIDENCE`).

**Further frozen #248 function-level comparison:** The entire
`development_git_delivery.py` blob, including `GitDraftPublisher`,
is identical. In `local9b_issue_bridge.py`,
`_gh` and `previous_issue_attempt` are unchanged; `issue_task`,
`collect_ready` and `resolve_task` retain their older ready-label,
fixed contract, one-shot and fresh-Issue checks while adding dependency,
priority and scope revalidation (`PRESERVED_WITH_HARDENING`).
`development_host.py` retains identical `LocalDevelopmentGateway`
and `LocalDevelopmentFilesystem`; its Harness proposal path adds
compile-without-execution, while its task entry adds optional host-bounded
repair/review/compact-edit handling. `development_loop.py` preserves bounded
Guard writes and Draft delivery and tightens fixed-test acceptance with
typed subprocess receipts (`SUPERSEDED_WITH_EVIDENCE`).

These findings are **scoped to the compared function bodies**. They are not
52/52 semantic equivalence, never permission to replay historical Native
effects, and never a statement about the installed M1 release.

**Outstanding acceptance:** remaining old PR function-level gaps; actual
M1 deployment/readback, owner-authenticated MCP and private view binding;
real owner-reconstruction fidelity; one unattended approved autonomous
development task from discovery through independent Draft verification.
A code merge or queued/green synthetic CI is not that live E2E proof.
