// Fixed public ACP agent fixture. No provider, model, keys, shell or network.
import { createInterface } from 'node:readline'

const response = (message) => process.stdout.write(JSON.stringify(message) + '\n')
let session = false
const seen = []
for await (const line of createInterface({ input: process.stdin, crlfDelay: Infinity })) {
  if (line.length > 8192) process.exit(31)
  let req
  try { req = JSON.parse(line) } catch { process.exit(32) }
  if (req?.jsonrpc !== '2.0' || typeof req?.method !== 'string') process.exit(33)
  if (req.method === 'initialize') {
    if (seen.length !== 0) process.exit(34)
    seen.push('initialize')
    response({ jsonrpc: '2.0', id: req.id, result: {
      protocolVersion: 1,
      agentCapabilities: { promptCapabilities: { image: false, audio: false, embeddedContext: false } },
      authMethods: [],
    } })
  } else if (req.method === 'session/new') {
    if (seen.join(',') !== 'initialize' ||
        !Array.isArray(req.params?.mcpServers) ||
        req.params.mcpServers.length !== 0) process.exit(35)
    seen.push('session/new')
    session = true
    response({ jsonrpc: '2.0', id: req.id, result: { sessionId: 'public-fixture-session' } })
  } else if (req.method === 'session/prompt') {
    if (!session || seen.join(',') !== 'initialize,session/new' ||
        req.params?.sessionId !== 'public-fixture-session' ||
        JSON.stringify(req.params?.prompt) !==
          JSON.stringify([{ type: 'text', text: 'PUBLIC_ONLY_DSH_ACP_ONCE' }])) process.exit(36)
    seen.push('session/prompt')
    response({ jsonrpc: '2.0', method: 'session/update', params: {
      sessionId: 'public-fixture-session',
      update: { sessionUpdate: 'agent_message_chunk',
        content: { type: 'text', text: 'PUBLIC_DSH_ACP_PROMPT_COMPLETED' } },
    } })
    response({ jsonrpc: '2.0', id: req.id, result: { stopReason: 'end_turn' } })
  } else if (req.method === 'session/cancel') {
    process.exit(37)
  } else {
    process.exit(38)
  }
}
