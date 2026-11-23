# Vision capability plan

Status: production-complete for the accepted image/VISION path as of 2026-09-27; normal daily use is `foundation-auto` with Agent-selected VISION under host-authorized attachment authority. PDF, Office, audio and other non-image media remain separate capability gates.

## Canon fit
Vision is a generic reusable execution concern and belongs behind existing Foundation capability/routing/execution boundaries. It must not contain CAD/Qilin semantics and Foundation must not depend on CAD Reconstruction.

Canonical flow: upstream product -> owner-scoped attachment handoff -> trusted VISION capability request -> automatic Foundation route selection -> replaceable vision execution port -> local/cloud vision model -> structured non-authoritative observation -> caller-owned validation/evidence semantics.

The caller owns domain meaning. CAD Reconstruction retains authority for provenance, geometry Evidence promotion, part hypotheses, confidence and reconstruction state.

## Reuse, do not duplicate
Reuse CapabilityRequest, AttachmentHandoff, provider health/quota/budget/privacy machinery, local/cloud execution boundaries, observability/evaluation and HumanView conventions. Do not create a CAD-specific route/provider, Qilin heuristics, second attachment store/provider registry, model semantics in Guard, or authority from model output.

## Required generic changes
1. Add VISION to canonical route/capability namespace and trusted host mapping.
2. Define VISION topology as inference-consuming.
3. Make provider/local VISION support explicit and independently probed; never infer it from CHAT.
4. Accept host-authorized image attachment content without accepting arbitrary filesystem paths or remote URLs as authority.
5. Add a narrow replaceable VisionExecutionPort: task + owner-scoped image grants -> structured non-authoritative observation.
6. Preserve automatic routing/fallback/scarcity/privacy/budget rules; local and cloud multimodal models are ordinary VISION candidates.
7. Deterministically test normalization, trusted intake, owner mismatch/traversal, non-image rejection, unsupported provider, fallback, local-only/privacy, model failure and output schema.
8. Require real-host E2E before completion: upstream image -> Foundation -> selected VISION route -> structured result, with actual pixels observed and no authority escalation.

## First model PoC
Microsoft Florence-2-base (MIT) is only a replaceable first local candidate, not canon. Generic tasks include caption, object detection, phrase grounding, dense region caption and OCR. Larger VLMs may be compared behind the same contract.

## Completion gate
VISION is complete only when the generic capability/routing/intake/execution/observability paths are tested; at least one local or cloud candidate works through the same contract; attachments remain owner-scoped; outputs remain non-authoritative; a real upstream image request passes end-to-end; and replacing/removing the selected model requires no caller redesign.

## Phase 1 implemented — 2026-09-22
Canonical namespace, aliases, trusted CapabilityRequest attachment requirement, LLM-route topology, settings route visibility and explicit provider capability semantics are implemented and regression-tested. This does not claim image transport or model execution. OpenAICompat remains fail-closed for non-text until the attachment-to-vision transport gate is implemented.

## Execution convergence — 2026-09-27

Historical pre-acceptance checkpoint — superseded for current availability/completion status by `Production completion — 2026-09-27` below.

The generic VISION execution path is now composed through the production bootstrap without making VISION a ToolHive capability. `VisionExecutionPort` consumes the existing owner-scoped `AttachmentHandoff`; `RoutedVisionBackend` reuses the canonical `ComputeRouter`; local execution preserves runtime `execution_slot` separately from model identity and uses the loopback OpenAI-compatible image adapter. Cloud VISION remains fail-closed until an explicitly VISION-capable provider is configured.

Availability is also fail-closed: wiring a `vision_port` alone does not advertise a human-visible VISION execution path. Operator capability projection requires an eligible live VISION route. The current production inventory contains zero VISION candidates, so VISION remains unavailable rather than being falsely advertised.

Focused VISION/routing/Operator regression passed 94 tests. Full AI Foundation regression passed 1053 tests with 10 skipped, and the canonical live runtime-drift audit returned PASS. No production model, provider capability, manifest, credential, or process was changed to manufacture this evidence.

This advances the generic image/VISION implementation gate only. VISION is not production-complete: at least one explicit local or cloud VISION candidate must still be deployed through the existing capability contract, actual authorized pixels must cross the real production route and produce a pixel-dependent result, and the physical LibreChat upload E2E must pass. PDF, Office, audio, and other non-image media remain separate capability gates.

## Production completion — 2026-09-27

The earlier `Execution convergence` checkpoint is superseded for current status. A production VISION candidate is now active through the existing generic route/execution contract, and the completion gate defined above has been exercised with real authorized pixels.

The accepted physical path is normal daily-use `foundation-auto`, not a user-selected VISION shortcut: browser image upload -> owner-scoped LibreChat attachment lookup/handoff -> signed CHAT request with host-authorized attachment IDs -> Pydantic AI Agent -> Agent-selected VISION tool -> CapabilityExecutor -> selected VISION route -> actual-pixel observation -> grounded final response. The explicit `foundation-vision` identity remains a diagnostic/verification alias.

Authority and media safety remain fail-closed. Owner mismatch, trusted-root escape, traversal, missing authority, signing tamper, auxiliary-call authority inheritance, invalid/non-image/oversize input, and raw symlink attachment boundaries are regression-covered. A reproduced raw-symlink bypass was fixed at both AttachmentHandoff and VisionExecutionPort before final acceptance; the VISION backend is not invoked for that rejected input.

Final post-fix regression is `1067 passed, 10 skipped` with one known `pydantic_graph` deprecation warning; runtime-drift contract is `3 passed`. The production LibreChat image is `ai-foundation/librechat:v0.8.7-vision-candidate-tdzfix` (`sha256:8077998f10929aa3e281839dcf848c2bb7fb99ab960b419516a214e31f77bb11`).

The generic image/VISION completion gate is therefore closed for the accepted production image path. Model replacement remains behind the same candidate/route/backend contracts and must not require caller redesign. PDF, Office, audio, and other non-image media remain separate capability gates.
