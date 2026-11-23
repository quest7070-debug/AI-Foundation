// Real official DSH ACP backend -> one public scripted ACP child prompt.
// Isolated CI-only package installation; no OpenCode provider or network.
import { readFileSync } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { Context, Service } from '@deepseek-ai/cordis'
import SessionStore, { SessionId } from '@deepseek-ai/dsh-session'
import AgentRegistry from '@deepseek-ai/dsh-agent'
import SessionProjectionRegistry from '@deepseek-ai/dsh-session-projection'
import SubagentRuntime from '@deepseek-ai/dsh-subagent'
import LocalSubprocessRuntime from '@deepseek-ai/dsh-subprocess-local'
import * as Acp from '@deepseek-ai/dsh-subagent-acp'

class PublicWorkingDirectory extends Service {
  constructor(ctx) { super(ctx, 'workingDirectory') }
  get(session) { return session.header.cwd ?? process.cwd() }
  async ensure(agent, signal) { signal?.throwIfAborted(); return this.get(agent.session) }
  async set() { throw new Error('FIXTURE_CWD_IMMUTABLE') }
}

const [patchFile, childFile] = process.argv.slice(2)
const offlineMode = process.argv[4] === '--offline-opencode'
if (process.argv[4] && !offlineMode) throw new Error('UNSUPPORTED_TEST_MODE')
const imageId = offlineMode ? (process.argv[6] ?? '') : ''
const docker = process.env.FOUNDATION_DOCKER_BINARY ?? ''
const endpoint = process.env.FOUNDATION_DOCKER_HOST ?? ''
const publicPrompt = offlineMode ? readFileSync(process.argv[5], 'utf8').trimEnd() : ''
if (offlineMode && (
    !/^sha256:[a-f0-9]{64}$/.test(imageId) ||
    imageId === 'sha256:57f8be0db1ea76562a43d732c18efe5bdb447e29f371e8aab2fd4f5f88b92bfc' ||
    !['/opt/homebrew/bin/docker','/usr/local/bin/docker'].includes(docker) ||
    !/^unix:\/\/[\/A-Za-z0-9_.-]{8,300}$/.test(endpoint) ||
    (await import('node:crypto')).createHash('sha256').update(publicPrompt).digest('hex') !==
      '327e74a2962625a5936ad88b45226dc2b205ba92734b4f5439a922676c43584c'
)) throw new Error('OFFLINE_REVIEWED_HOST_REQUIRED')
const offlineWorker = "import sys,os,hashlib,json,subprocess,threading\nfrom ai_foundation.opencode_docker_isolation import _netns_isolated\nfrom ai_foundation.opencode_model_gate import OfflineOpenCodeModelGate,OpenCodeFixtureServer,opencode_v2_isolated_config\np='/usr/local/bin/opencode'\nif sys.platform!='linux' or os.getuid()!=65534 or not _netns_isolated()[0]: sys.exit(41)\nwith open(p,'rb') as f:\n h=hashlib.sha256()\n for b in iter(lambda:f.read(1048576),b''): h.update(b)\nif h.hexdigest()!='2d719ef7b593a3e836dab611bc28da0e9ee71958d5e72ddb41e0f6abe2924e14': sys.exit(42)\ngate=OfflineOpenCodeModelGate()\nmessage_keys=[]\noriginal_validate=gate.validate\ndef checked_validate(body):\n if type(body) is dict and type(body.get('messages')) is list:\n  known=('role','content','name','providerOptions','providerMetadata','metadata','cache_control','id','tool_call_id','tool_calls','parts','refusal','annotations','experimental_providerMetadata','provider_options','provider_metadata','extra')\n  for m in body['messages'][:3]:\n   if type(m) is dict:\n    message_keys.append({'known':[k for k in known if k in m], 'unknown':sum(k not in known for k in m),'count':len(m)})\n return original_validate(body)\ngate.validate=checked_validate\nserver=OpenCodeFixtureServer(gate)\nthread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()\nenv={'PATH':'/usr/bin:/bin','HOME':'/tmp','XDG_CONFIG_HOME':'/tmp/config','XDG_STATE_HOME':'/tmp/state','XDG_DATA_HOME':'/tmp/data','XDG_CACHE_HOME':'/tmp/cache','OPENCODE_DB':'/tmp/opencode.db','OPENCODE_PURE':'1','OPENCODE_DISABLE_PROJECT_CONFIG':'1','OPENCODE_DISABLE_EXTERNAL_SKILLS':'1','OPENCODE_DISABLE_AUTOUPDATE':'1','OPENCODE_DISABLE_MODELS_FETCH':'true','OPENCODE_DISABLE_FILEWATCHER':'true','OPENCODE_CONFIG_CONTENT':json.dumps(opencode_v2_isolated_config(server.server_port),separators=(',',':'))}\nrc=43\ntry:\n child=subprocess.Popen([p,'acp'],stdin=sys.stdin.fileno(),stdout=sys.stdout.fileno(),stderr=subprocess.DEVNULL,env=env,cwd='/tmp')\n try: rc=child.wait(timeout=70)\n except subprocess.TimeoutExpired:\n  child.kill();child.wait();rc=44\nfinally:\n server.shutdown();server.server_close();thread.join(timeout=2)\n sys.stderr.write('DSH_OPENCODE_GATE='+('ONE_PUBLIC_ONLY' if gate.accepted==1 and gate.denied==0 else 'NOT_ACCEPTED')+';accepted='+str(gate.accepted)+';denied='+str(gate.denied)+';reason='+','.join(sorted(gate.denial_reasons))+';child_exit='+str(rc)+'\\n')\nif gate.denied_shapes:\n sys.stderr.write('DSH_OPENCODE_MESSAGE_KEYS='+json.dumps(message_keys[:3],sort_keys=True,separators=(',',':'))+'\\n')\n s=gate.denied_shapes[0]\n keep=('message_count','message_roles','public_prompt_present','public_prompt_in_user','user_content_type','user_content_length','user_prefix_tags','user_suffix_tags','user_trimmed_exact','system_fingerprint','system_length','tools_fingerprint','tools_count','has_tools','has_system','has_metadata','has_tool_choice','has_response_format')\n sys.stderr.write('DSH_OPENCODE_SHAPE='+json.dumps({k:s.get(k) for k in keep},sort_keys=True,separators=(',',':'))+'\\n')\nsys.exit(0 if rc==0 and gate.accepted==1 and gate.denied==0 else 45)";

if (!patchFile || !childFile) throw new Error('MISSING_REVIEWED_PATCH')
const layers = JSON.parse(readFileSync(patchFile, 'utf8'))
const rows = layers?.[0]?.insert
if (!Array.isArray(rows) || rows.length !== 2) throw new Error('PATCH_SHAPE')
const backend = rows[0], tool = rows[1]
if (backend.name !== '@deepseek-ai/dsh-subagent-acp' ||
    tool.name !== '@deepseek-ai/dsh-tool-subagent' ||
    backend.config.providerName !== 'foundation-opencode' ||
    backend.config.permission !== 'reject' ||
    tool.config.provider !== 'foundation-opencode' ||
    tool.config.toolName !== 'subagent_opencode' ||
    backend.config.env.OPENCODE_DISABLE_MODELS_FETCH !== 'true') {
  throw new Error('PATCH_REVIEW_FAILED')
}
// Override the executable only in this synthetic no-model acceptance lane.
// The staged production command is never started or authorized.
const ctx = new Context()
let stage = 'PROJECTION'
let parentRegistered = false
let scopeRegistered = false
try {
  // Match the official rc.1 ACP backend test composition:
  // mount projection, directory and subagent first; register the parent
  // Agent/session after the backend has been composed.
  await ctx.plugin(SessionProjectionRegistry)
  stage = 'WORKING_DIRECTORY'
  await ctx.plugin(PublicWorkingDirectory)
  stage = 'SUBAGENT_RUNTIME'
  await ctx.plugin(SubagentRuntime, { maxDepth: 1, maxActiveSubagents: 1 })
  stage = 'SUBPROCESS_RUNTIME'
  await ctx.plugin(LocalSubprocessRuntime)
  stage = 'ACP_BACKEND'
  const childLaunch = offlineMode ? {
    command: docker,
    args: ['run','--rm','-i','--pull=never','--network=none',
      '--platform=linux/arm64','--read-only','--user=65534:65534',
      '--cap-drop=ALL','--security-opt=no-new-privileges',
      '--pids-limit=64','--memory=768m','--cpus=1','--ipc=none',
      '--tmpfs=/tmp:rw,nosuid,nodev,size=128m','--workdir=/tmp',
      '--env=HOME=/tmp','--entrypoint=python3',imageId,
      '-u','-c',offlineWorker],
    env: { DOCKER_HOST: endpoint, HOME: process.env.HOME,
      PATH: '/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin' },
  } : { command: process.execPath, args: [childFile], env: {} }
  await ctx.plugin(Acp, {
    ...backend.config, ...childLaunch,
    disposeEofGraceMs: offlineMode ? 4000 : 1200,
    disposeGraceMs: offlineMode ? 3000 : 800,
  })
  stage = 'SESSION_STORE'
  await ctx.plugin(SessionStore)
  stage = 'REGISTRY'
  await ctx.plugin(AgentRegistry)
  stage = 'SESSION_CREATE'
  const session = ctx.sessions.create(SessionId(randomUUID()), {
    meta: { cwd: process.cwd() },
  })
  const inbox = { append() {}, clear() {} }
  const parent = {
    id: session.id, session, ctx, options: {}, status: 'idle',
    model: { current() { throw new Error('PUBLIC_MODEL_FORBIDDEN') },
      select() { throw new Error('PUBLIC_MODEL_FORBIDDEN') } }, inbox,
    send: (msg, target) => inbox.append(target, msg),
    followup: (msg) => inbox.append('next-turn', msg),
    steer: (msg) => inbox.append('next-step', msg),
    inject: (msg) => inbox.append('next-step', msg),
    cancel: () => inbox.clear(),
    whenIdle: () => Promise.resolve(),
    runMaintenance: task => task(new AbortController().signal),
  }
  stage = 'PARENT_REGISTER'
  await ctx.agents.register(parent)
  stage = 'PARENT_VERIFY'
  parentRegistered = ctx.agents.get(parent.id) === parent
  scopeRegistered = ctx.subagents.ctx?.get('agents')?.get(parent.id) === parent
  if (!parentRegistered || !scopeRegistered) {
    throw new Error('DSH_PARENT_SCOPE_NOT_REGISTERED')
  }
  stage = 'DELEGATE_START'
  const run = await ctx.subagents.startActivation({
    provider: backend.config.providerName,
    label: 'Public fixed ACP prompt',
    request: {
      cwd: offlineMode ? '/tmp' : process.cwd(),
      prompt: [{ type: 'text', text: offlineMode ? publicPrompt : 'PUBLIC_ONLY_DSH_ACP_ONCE' }],
      parent,
    },
    signal: AbortSignal.timeout(25000),
    delivery: 'caller',
  })
  stage = 'DELEGATE_RESULT'
  const result = await run.result
  stage = 'DELEGATE_DISPOSE'
  if (offlineMode) console.log('DSH_OPENCODE_STOP_REASON='+
    (['completed','error','aborted','refusal','max-tokens'].includes(result.stopReason) ? result.stopReason : 'UNCLASSIFIED'))
  await run.dispose()
  const output = result.output.filter(b => b.type === 'text').map(b => b.text).join('')
  if (result.stopReason !== 'completed' ||
      (offlineMode ? output.trim() !== 'def add(x, y):\n    return x + y' :
        output !== 'PUBLIC_DSH_ACP_PROMPT_COMPLETED')) {
    throw new Error('ACP_PROMPT_TERMINAL_NOT_ACCEPTED')
  }
  console.log(offlineMode
    ? 'DSH_ACP_PROMPT=OFFICIAL_BACKEND_REAL_OPENCODE_OFFLINE_ACCEPTED'
    : 'DSH_ACP_PROMPT=OFFICIAL_BACKEND_SYNTHETIC_CHILD_ACCEPTED')
  console.log('DSH_ACP_PROVIDER_CALLS=0')
} catch (error) {
  console.log('DSH_ACP_PROMPT=NOT_ACCEPTED')
  console.log('DSH_ACP_FAILURE_CLASS=' + (error?.name || 'UNCLASSIFIED'))
  const allowedCodes = new Set([
    'UNAUTHORIZED', 'UNSUPPORTED_CAPABILITY', 'PROVIDER_NOT_FOUND',
    'ACTIVATION_LIMIT_REACHED', 'CONTINUATION_UNAVAILABLE',
    'PROVIDER_CHANGED', 'INVALID_AGENT_NAME', 'SUBAGENT_DENIED',
  ])
  const code = String(error?.code || '')
  console.log('DSH_ACP_FAILURE_CODE=' +
    (allowedCodes.has(code) ? code : 'UNCLASSIFIED'))
  console.log('DSH_ACP_FAILURE_STAGE=' + stage)
  console.log('DSH_ACP_PARENT_IN_ROOT=' + parentRegistered)
  console.log('DSH_ACP_PARENT_IN_PROVIDER_SCOPE=' + scopeRegistered)
  // This lane has a no-key ephemeral HOME, but never print raw exception text.
  const message = String(error?.message || '')
  const hint = /reading ['"][a-zA-Z]+['"]/.exec(message)?.[0]
    ?? (/not a function/.test(message) ? 'NOT_A_FUNCTION'
       : /not defined/.test(message) ? 'NOT_DEFINED'
       : /cannot be used/.test(message) ? 'INVALID_CALL'
       : 'UNCLASSIFIED')
  console.log('DSH_ACP_FAILURE_HINT=' + hint)
  const safeFrames = String(error?.stack || '').split('\n').slice(1, 5)
    .map(line => {
      const match = /\bat\s+([A-Za-z_$][A-Za-z0-9_.$<>]*)/.exec(line)
      return match?.[1] ?? 'ANONYMOUS'
    })
  console.log('DSH_ACP_FAILURE_CALLS=' + safeFrames.join(','))
  console.log('DSH_ACP_RUNTIME_CONFIG_PRESENT=' + Boolean(ctx.subagents?.config))
  process.exitCode = 2
} finally {
  await ctx.fiber.dispose()
}
