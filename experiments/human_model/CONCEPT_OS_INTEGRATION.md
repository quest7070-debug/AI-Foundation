# HumanModel ↔ Concept OS integration contract (2026-11-01)

Source: archived Concept OS decisions and 「AI機会審査」 discussion. This
document records compatibility constraints, **not** proof of a working integration.

## Preserve the boundary

1. **Raw-first**: Chat, Concept, Opportunity, Review, Feedback, External,
   Manual remain source records. AI interpretation is a derived proposal,
   not the canonical user profile. Source provenance and revision must survive.
2. **Context Builder is transport**: it fetches records, traverses explicit
   operational links, and applies size limits. It must not infer semantic
   relationships, user interests, importance, or decide Concept quality.
3. **Human decision**: Opportunity→Chat, Chat→Concept, Concept→Review require
   explicit user actions. AI cannot silently confirm a Concept or opportunity.
4. **No frozen personality**: for personalized Concept review, interpret
   current authorized Raw afresh; do not serve cached user-character judgments
   as facts. Derived hypothesis snapshots may be retained for *audit and
   comparison*, but must not silently become authoritative personalization.
5. **Discovery ≠ recommendation**: external Raw is collected broadly, including
   unfamiliar sources. Compare to known/experienced concepts for *distance*,
   not just similarity or inferred likes. Semantic distance is recalculated
   at evaluation time; do not cache it as a stable user attribute.
6. **Review objective/personal separation**: axis score + observed real-world
   value + reason, then objective aggregate. Personal commentary is a separate
   stage with explicitly authorized Raw. Do not use predicted preferences to
   fabricate objective values.
7. **Append-only revisions**: repeated Review and Good/Bad/free-text Feedback
   are preserved as Raw with provenance; Feedback never automatically becomes
   a personality instruction.
8. **Multi-model dissent**: keep producer, revision, contradictory evidence,
   and uncertainty; no forced consensus. Hypotheses are provisional.

## Mapping to existing code

- `human_model_ledger.py`: scoped source evidence, supersession, revision,
  source trace, view invalidation; not a substitute for original Raw.
- `foundation_readonly.py`: purpose-scoped read-only view; caller
  authentication and Guard policy still require runtime enforcement.
- `hypothesis_engine.py`, `temporal_comparison.py`: provisional
  evidence-grounded hypotheses and audit snapshots, **not** a fixed user model.
- `proposal_json_contract.py`, `ollama_proposal_runner.py`: untrusted
  model output contract; no Concept acceptance, feedback ingestion, or
  scheduled opportunity discovery is implemented.

## Implementation priorities

P0: align canonical privacy levels (shareable/restricted/private), exercise
real adapter tests, and prove M1 Ollama synthetic execution.

P1: add source-linked Raw ingestion with consent, revisions and provenance;
add explicit user decision event contracts and objective/personal review split.

P2: separate opportunity discovery over external Raw from HumanModel;
compute distance dynamically; connect through stable IDs only.

P3: evaluate actual multi-producer disagreement and temporal changes against
user-corrected outcomes without collapsing competing interpretations.

## Not authorized

Do not automatically import past chats, audio or private files into the real
external SSD ledger. Do not auto-approve Concepts, auto-convert feedback into
rules, or treat model-generated psychological claims as facts.
