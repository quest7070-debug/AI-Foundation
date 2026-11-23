# HumanModel user decision events (2026-11-01)

Contract for the transitions the integration boundary reserves to the
user: `opportunity_to_chat`, `chat_to_concept`, `concept_to_review`
(see `CONCEPT_OS_INTEGRATION.md` in PR #77, "Human decision").

## Rules

1. **User-only**: a decision event names `actor="user"`. AI, model or
   system actors are refused at the contract level. This is a contract
   check, not caller authentication; Guard/process isolation remain a
   runtime responsibility.
2. **Explicit**: the action is `accept` or `reject`. There is no default,
   no silent confirmation, and absence of a decision means *undecided*,
   never approval.
3. **Target-bound**: the event cites an existing evidence id in the
   identical scope. Missing or cross-scope targets are refused.
4. **Append-only**: decisions are Ledger evidence (`kind="decision"`)
   with a canonical JSON payload. Corrections are new events that
   supersede the earlier decision; history is retained for audit.
5. **Idempotent**: re-recording the identical event returns the existing
   evidence id. Reusing an event id with a different payload is refused.
6. **Data, not instruction**: a recorded decision does not execute the
   transition, approve a Concept, or convert feedback into rules. A
   consumer must read `current_decision` and act under its own gates.

## Not implemented here

No UI, no caller authentication, no automatic transition execution, and
no ingestion of real chats or private Raw. Synthetic tests only.
