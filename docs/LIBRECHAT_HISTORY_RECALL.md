# LibreChat cross-conversation history recall

History ownership remains outside AI Foundation.

Runtime flow: LibreChat searches its own user-scoped Meilisearch messages index, excludes the current conversation, revalidates candidate IDs against live MongoDB rows, injects at most six live messages as untrusted historical context, then sends an ordinary prompt to Foundation.

The runtime patch is deploy/librechat-v0.8.7-history-recall.patch. It is based on the known-good ai-foundation/librechat:v0.8.7-signing client and intentionally does not import newer LibreChat Agent APIs. This prevents source/package skew such as getDynamicToolContexts is not a function.

Production runtime image: ai-foundation/librechat:v0.8.7-history-compatible.

LIBRECHAT_HISTORY_RECALL=true enables recall. The existing history-search MCP remains hidden from the chat menu and is not part of the Foundation request path.

Upgrade rule: never copy a whole Agent client from a different LibreChat revision. Rebase this small patch onto the target LibreChat version and verify its package exports first.
