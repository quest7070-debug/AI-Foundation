# LibreChat v0.8.7 final-body signing boundary

Production image inspection proves the Foundation custom endpoint reaches `@langchain/openai` `ChatOpenAICompletions.completionWithRetry`, which calls OpenAI SDK `client.chat.completions.create(request, clientOptions)`. The installed OpenAI SDK then builds the final body through `FallbackEncoder` as `JSON.stringify(body)` before `fetchWithTimeout` calls the configured `fetch(url, init)` with `init.body` already serialized.

Therefore the safe integration point is a Foundation-only custom `configuration.fetch` supplied through `getOpenAIConfig`/`configOptions`. That wrapper must sign `init.body` bytes at call time and add v2 headers to a cloned request. It must not sign Express `req.body`, model input, or reconstructed JSON. Non-Foundation endpoints must keep the default fetch unchanged. Secret input remains the read-only runtime secret file. Owner/capability/scope/attachment metadata must be server-derived before the wrapper is constructed.

Deployment gate: implement this only in an exact v0.8.7 disposable patch, run node syntax/module checks, then isolated upstream capture proving received raw bytes verify at Gateway v2. Only after that may production be considered.

## v0.8.7 server-derived attachment source

Runtime source trace confirms the request file authority does not need to come from browser-provided paths. `api/server/services/Endpoints/agents/initialize.js` takes only request file IDs from `req.body.files`, then `initializeAgent` calls `db.updateFilesUsage(requestFiles, ..., { user: req.user.id, tenantId: req.user.tenantId })`. The resulting owner-scoped Mongo file records are filtered by endpoint config and passed through `primeResources` as `requestAttachments`; `AgentClient` receives `primaryConfig.requestAttachments`. Therefore a Foundation signing context must derive attachment IDs from those post-lookup `requestAttachments` records (or an equivalently owner-scoped server result), never directly from raw `req.body.files`. The signing owner is `req.user.id`; tenant remains part of the lookup boundary but is not an HMAC authority field.

Integration implication: the current disposable patch's `req.__foundationAuthorizedAttachments` placeholder has no production writer and is incomplete. The correct patch point is after `initializeAgent` has produced `primaryConfig.requestAttachments`, before the model run is constructed. Bind only their `file_id` values into the Foundation signing context that reaches `configuration.fetch`. A forged/missing raw file ID must therefore disappear or fail during the existing owner-scoped DB lookup before signing.

### Disposable patch correction: normalized provider identity
The v0.8.7 provider resolver normalizes a custom endpoint such as `Foundation` to `overrideProvider = openAI` after resolving `customEndpointConfig`. Therefore the post-lookup attachment snapshot must be gated by `customEndpointConfig?.name === "Foundation"`, not `provider === "Foundation"`. The disposable bundle has been corrected accordingly and now snapshots only `requestAttachments` after priming. `node --check` passes. This patch remains disposable/not deployed.
