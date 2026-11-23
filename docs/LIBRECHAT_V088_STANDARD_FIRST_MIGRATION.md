# LibreChat v0.8.8 standard-first migration audit

Status: ACCEPTED MIGRATION CANDIDATE / PRODUCTION UNCHANGED
Date: 2026-10-07

## Decision

The next personal-AI capability expansion MUST evaluate LibreChat v0.8.8 standard ownership before adding Foundation product code. Production remains on the accepted v0.8.7-derived image until an isolated v0.8.8 candidate preserves Foundation authority, attachment and signing invariants and passes regression plus physical acceptance.

Official isolated source audited: LibreChat v0.8.8 commit `e8f3be08623663d4ad7f7241e693c94469b63bb0`.

## Standard ownership confirmed

- Memory: True
- Projects: True
- Schedules: True
- MCP: True
- programmatic_tools: True
- webSearch: True
- fileSearch: True
- memories: True
- mcpServers: True

## Current production and migration rules

- Production remains `ai-foundation/librechat:v0.8.7-vision-candidate-tdzfix`; MongoDB, Meilisearch, RAG API and pgvector are already running.
- Current configuration intentionally disables memories, agents, runCode, webSearch, fileSearch and MCP UI; the existing history-search MCP is read-only.
- `deploy/librechat-v0.8.7-foundation-signing.patch` is a security/authority boundary and MUST NOT be discarded merely because v0.8.8 exists.
- `deploy/librechat-v0.8.7-history-recall.patch` MUST first be compared with v0.8.8 standard Memory/search and should be deleted if standard behavior closes the use case.
- Both v0.8.7 patches fail direct apply against v0.8.8; semantic reconciliation is required. Blind replay is forbidden.
- Prefer standard Memory, Projects, Scheduled Chats, MCP, Web/File Search and programmatic tools before custom code.
- Rebase only the minimum remaining Foundation authority/signing/owner-scoped attachment adapter. Do not recreate LibreChat product features.
- No new Foundation Memory DB, Project subsystem, scheduler clone, generic MCP catalog clone or Deep-Research subsystem is authorized without a demonstrated residual gap.
- Zero-additional-cost routes first. Paid API, credit purchase, automatic upgrade and automatic billing are not authorized.
- Production switch requires isolated acceptance of CHAT, history/memory, FILES/attachments, VISION, SEARCH, MCP and scheduling, Foundation regression, and immediate rollback to the current known-good image/config.

## Responsibility

LibreChat owns presentation/workspace features and its native Memory, Projects, Schedules, MCP and search UI. Foundation owns semantic policy, authority, privacy, provider/local routing, evidence, verification and its product durable-work boundary. Kandev remains the development execution plane.
