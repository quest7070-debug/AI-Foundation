# Vision execution implementation plan — 2026-09-22


## Current status supersession — 2026-09-27

The open production/model/E2E statements below are historical implementation-plan state from 2026-09-22.

They are superseded for current status by the later production acceptance recorded in `CURRENT_STATE.md`, `ROADMAP.md`, `FULL_SYSTEM_VERIFICATION_MATRIX.md`, and `PROGRAM_COMPLETION_2026-09-27.md`.

The accepted current image/VISION path is production-complete through normal `foundation-auto`, including real-model actual-pixel physical E2E. PDF, Office, audio and other non-image media remain separate future capability gates.

This file remains useful as implementation history and design rationale; its earlier open-gate wording must not be interpreted as current production truth.

This plan was reconciled against every document under docs/ before implementation. Existing canon wins: Guard owns privacy/authority/budget semantics; attachments remain owner-scoped; routing is capability-first; provider/model implementations remain replaceable; model output is observational data, never authority.

## Minimal completion sequence
V1 Contract (done): VISION namespace, trusted attachment requirement, inference topology, explicit provider capability.
V2 Execution boundary: add VisionExecutionPort + VisionObservation; consume only trusted AttachmentGrant; lease handoff during inference; validate regular image file and bounded type/size; invoke replaceable backend; return structured non-authoritative observation. No CAD semantics.
V3 Host/intake + routing (implemented): CapabilityExecutor dispatches VISION. OpenAICompat accepts image content only when trusted VISION CapabilityRequest already contains host-resolved grants; client URLs/paths/base64 never become filesystem authority. Candidates explicitly advertise VISION.
V4 Adapter + E2E: wire one replaceable implementation, initially Florence-2 only if calibration passes. Test real pixels, owner mismatch, traversal/symlink/non-image/oversize, backend failure, privacy local-only, fallback and schema. Only then production-complete.

## Anti-coupling rules
CAD imports no Foundation internals; Foundation imports no CAD code. Florence-2 is an adapter candidate, not canon. CHAT does not imply VISION. VISION observations create neither Effects nor Evidence. Existing capabilities remain unchanged.

## V3 implementation — 2026-09-22
OpenAICompat now permits image content markers only under a trusted VISION envelope containing host-resolved AttachmentGrant objects. Client URL/base64/path values are ignored as authority. The operator advertises Foundation Vision and exposes a human-visible VISION execution path only when a VisionExecutionPort is actually wired.

## Reuse/coupling audit — 2026-09-22
The transfer layer is intentionally not a CAD/VISION-only transport. AttachmentRecord -> AttachmentHandoff.resolve -> AttachmentGrant -> CapabilityRequest is the generic owner-scoped host data handoff already shared with attachment-bearing capabilities. VISION consumes that contract rather than defining a second store or path protocol. LibreChat integration is a metadata lookup adapter: owner + opaque attachment ID maps to the generic record and exposes no product semantics downstream.

Only validation/execution after the generic grant boundary is image-specific. Future audio/document/media capabilities must reuse AttachmentHandoff/AttachmentGrant and add their own post-grant validators/execution ports rather than extending VisionExecutionPort or introducing product-specific transfer stores.

## V4a automatic routing — 2026-09-22
Vision backend selection now reuses ComputeRouter and the same explicit capability inventory used by Foundation inference. CHAT-only candidates cannot satisfy VISION. Local-required never falls to cloud. Failed candidates are excluded and the next eligible VISION route is attempted. Model-specific execution remains behind injected local/cloud factories; no Florence/CAD semantics enter routing. Real adapter + real-pixel E2E remain open.

## V4b adapter contract — 2026-09-22
A generic loopback OpenAI-compatible image adapter is implemented. It sends actual authorized image bytes as standard image content and contains no model/product semantics. Local discovery supports a host-owned vision slot with explicit VISION capability. No production model is configured by this change; measured model deployment and real-pixel E2E remain open.

## 2026-09-23 convergence decision

The execution plan was re-audited against the current production source after SEARCH, CODE and FILES-read convergence.

Focused VISION regression is green (39 passed), but production still has no eligible VISION route. The remaining gap is composition/integration, not a need to rebuild the existing VISION execution contract.

Constraints for the next implementation:

- no Gemini-only or other provider-specific VISION shortcut;
- no prompt/keyword/filename semantic router;
- no attachment-to-directory authority expansion;
- no inference of VISION from CHAT;
- no reopening of converged SEARCH/CODE/FILES authority without an observed regression;
- no settings/Human Decision Surface redesign;
- no broad provider/model capability refactor merely to close VISION.

Reuse the existing explicit candidate-capability contract, ComputeRouter, RoutedVisionBackend, AttachmentGrant/Handoff and VisionExecutionPort. Add production candidates and wiring through those boundaries. `foundation-auto` remains the intended daily-use entry and should gain VISION as an Agent-selected tool only when the host has supplied the required attachment authority and the execution path is genuinely available.

Completion still requires actual pixels to cross the real production path and produce a pixel-dependent result, followed by a physical LibreChat upload E2E. Unit/integration tests or a configured route alone are insufficient.

## 2026-09-27 composition convergence

Historical pre-acceptance checkpoint — superseded for current availability/completion status by `2026-09-27 production acceptance closure` below.

The 2026-09-23 statement that composition/integration remained open is superseded. Production bootstrap now constructs the generic VISION execution path independently of ToolHive and binds it to the existing owner-scoped attachment handoff. `RoutedVisionBackend` receives the selected `ComputeRoute`, preserving `execution_slot` versus model identity; the local factory uses `execution_slot or model` against the existing loopback llama-swap-compatible endpoint. No provider-specific shortcut or CAD semantics were added.

The Operator availability contract was hardened at the same boundary: `vision_port` existence is insufficient to advertise VISION; an eligible route must also exist. Focused regression passed 94 tests, full regression passed 1053 with 10 skipped, and canonical runtime drift is PASS.

Production inventory currently has zero explicit VISION candidates. Therefore the implementation is wired but unavailable, by design. No model or provider capability was added merely to close the audit. V4 real-pixel acceptance remains open exactly as specified above: deploy or configure an explicit VISION candidate through the existing contract, prove actual authorized pixels influence the result through the production path, then complete physical LibreChat upload E2E.

## 2026-09-27 production acceptance closure

The preceding composition checkpoint is superseded for current status: production no longer has zero VISION candidates, and V4 actual-pixel acceptance is complete for the accepted image path.

A real LibreChat browser upload traversed the intended normal path: `foundation-auto` remained signed CHAT, host-resolved owner-scoped attachment authority caused the Pydantic AI Agent to receive/select VISION, `CapabilityExecutor` executed VISION through the production route, actual image pixels were observed, and the tool result was synthesized into the final grounded response. No prompt classifier, filename classifier, provider-specific shortcut, directory-authority expansion, or CAD coupling was introduced.

The production LibreChat signing integration was also corrected before acceptance. The first candidate exposed a JavaScript temporal-dead-zone defect by consulting `customEndpointConfig` before initialization on attachment requests. The corrected candidate derives the authority decision from the already initialized `agent.endpoint`, adds only the audited VISION capability/mode delta, and preserves auxiliary-call stripping.

Security closure includes deterministic owner mismatch, root containment/traversal, no-authority, signing tamper, auxiliary isolation, type/size, backend-failure, and raw-symlink rejection. The raw-symlink case was first reproduced against both AttachmentHandoff and VisionExecutionPort, then fixed by rejecting the unresolved raw path before resolution/backend use.

Final post-fix full regression: `1067 passed, 10 skipped`, one known `pydantic_graph` deprecation warning. Runtime-drift contract: `3 passed`. After controlled Operator-only reload, normal `foundation-auto` CHAT remained healthy while Gateway, llama-swap and LibreChat were not restarted.

V4 is therefore closed for image/VISION. `foundation-auto` remains the daily-use entry; `foundation-vision` remains diagnostic/verification only. PDF, Office, audio and other media must reuse the generic attachment authority boundary but retain their own validation/execution/acceptance gates.
