# HumanModel evidence audit integration — 2026-11-02

Status: design contract only; not deployed. Preserve existing Raw Inbox and audit data.

## Purpose
Move the opportunity-history recovery audit into a reusable HumanModel evidence-audit pipeline, while preserving Concept OS as a separate consumer. This does not make assistant recommendations into user decisions.

## Source contracts
- Raw Inbox implementation: PR #81, `experiments/human_model/raw_inbox.py` and `RAW_INBOX_INTEGRATION_20261101.md`. Do not assume PR #81 is on main.
- Opportunity audits: previously merged PR #78 and follow-up PR #95; preserve source-quality and correction lineage.
- The 06:00 opportunity automation and the 07:00 recovery audit have distinct automation IDs and run IDs.

## Pipeline
1. Retrieve source through authorized connectors. Keep exact source URI, conversation ID, run ID, actor, timestamp (with timezone when known), source quality and truncation status.
2. Save complete original text to the verified private external-volume Raw Inbox. Refuse truncated automation results as complete Raw. No silent internal-disk fallback.
3. Independently append audit events referencing Raw ID and digest: source_discovered, gap_opened, source_verified, attribution_corrected, contradiction_linked, gap_resolved. Preserve original assertions and corrections; never rewrite historical judgments.
4. Separate assistant proposal, user question, explicit user acceptance, execution report and independently verified outcome. No inferred acceptance.
5. Optional later local-only Ollama review may propose candidate/defer/exclude; this is not HumanModel approval or Concept OS authorization.
6. Promote only explicitly approved evidence through a separate consent/authorization gate. Do not silently create personal Ledger entries.

## Minimum event fields
`event_id, source_raw_id, source_sha256, source_uri, source_message_ordinal_or_id, actor, event_type, observed_at, timestamp_quality, evidence_quality, linked_event_ids, supersedes_event_id, verification_status`.

Source ordinals are not internal ChatGPT message IDs. Unknown timestamps remain unknown. Secondary indexes cannot be promoted to direct transcripts.

## Migration acceptance
- Read-back of every Raw ID/digest from private SSD; idempotent replay; conflict detection.
- Recover prior audit chronology and unresolved gaps without duplicate candidate counts.
- Test Strata proposal -> user question -> assistant retraction without user acceptance.
- Test missing 2026-10-09..31 original transcripts remain gaps.
- Test no personal text in public GitHub, Actions, Issues or logs.
- Test no cloud/paid fallback, no model download, no automatic Ledger promotion.
- Preserve previous automation until parallel output comparison passes.

## Current limits
This document is a migration contract, not proof of M1 deployment, local SSD read-back, automation changes, or a successful end-to-end migration. Implement and verify these separately on an authorized private execution path.
