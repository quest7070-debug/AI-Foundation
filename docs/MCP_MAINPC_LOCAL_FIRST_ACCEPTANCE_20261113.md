# Integrated direct development: owner M1 and optional MainPC Strata

Status (2026-11-13): source integration complete; no claim of installed live MCP/Strata E2E.


## One-time transition from GitHub-as-runner to M1 local-first

On the **owner M1 with the reviewed revision already installed**, use the
existing trusted Foundation config path (not a model-supplied path):

```bash
python3 scripts/m1_strata_local_first_setup.py --config "$FOUNDATION_CONFIG"
python3 scripts/m1_strata_local_first_setup.py --config "$FOUNDATION_CONFIG" --apply
python3 scripts/mainpc_strata_preflight.py --config "$FOUNDATION_DATA_ROOT/local-compute/endpoints.json" --smoke
```

The live M1 read-only bridge on 2026-11-14 reported
`MAINPC_CONFIG_INVALID / KEY_BINDING` (Issue #1037), **not** confirmed
MainPC inference. For an existing entry matching the reviewed template in
every field except an *invalid* `api_key_env`, inspect first, then explicitly
repair only that one binding with:

```bash
python3 scripts/m1_strata_local_first_setup.py --config "$FOUNDATION_CONFIG" --repair-invalid-key-binding
python3 scripts/m1_strata_local_first_setup.py --config "$FOUNDATION_CONFIG" --repair-invalid-key-binding --apply
```

The repair pins only `STRATA_API_KEY`; it will not alter a valid
`MAINPC_STRATA_*` alias, any other endpoint, model, port, or host allowlist.
If the existing config differs in any other field, the result is
`EXISTING_ENDPOINT_REVIEW_REQUIRED` and nothing is changed. A real key still
must be present in the trusted owner environment; these commands neither
recover nor export a secret.

Use `--port 18080` only if the already-existing Windows portproxy is the
verified active endpoint; direct LAN 8080 is the default. The setup appends
the reviewed optional endpoint and preserves all other local routes. An
existing differently configured `mainpc-strata` is left untouched for review.
No credentials are written to disk: `STRATA_API_KEY` must already be provided
by the trusted owner launcher/environment. A missing or **empty** key disables
Strata, never attempts unauthenticated inference, and keeps the M1 fallback.

The authorized local AI client then launches the **existing**
`scripts/m1_owner_delegated_mcp_stdio.py --config "$FOUNDATION_CONFIG" --enable-local-development`
with a separately owner-reviewed, private `development/tickets.json`.
`development_run(ticket_id)` edits/tests locally; `development_status`
reads the durable local receipt; optional, separately approved
`development_deliver(ticket_id)` publishes a Draft GitHub PR only after
verified local acceptance. No GitHub Issue/Action round-trip occurs for
each revision. The Windows Strata instance is an inference backend,
**not** a second Guard/Host, an uncontrolled file-writing agent, or a
replacement for the M1 local execution path.

The setup is source-level until the exact installed revision and a real
authenticated MCP call are independently verified on M1. It does not
itself register a public/cloud MCP endpoint or install a Strata server.

This integration combines #958 and #959 without adding a second router,
scheduler, server, Work DB, API provider or Kandev executor. M1 is the Guard,
Host, Work, fixed acceptance and private data authority. Windows MainPC Strata
is one optional, host-owned CODE inference resource.

An installed M1 owner-local stdio MCP client can explicitly opt in by launching
scripts/m1_owner_delegated_mcp_stdio.py with its existing --config and
--enable-local-development. Omitting the opt-in retains the prior owner tools.
This is not cloud ChatGPT/Muse connectivity; a real authorized client must
still be installed and independently observed.

The trusted owner puts one regular 0600 JSON file at
DATA_ROOT/development/tickets.json under a 0700 development directory. Schema:

{
  "version": 1,
  "tickets": [{
    "ticket_id": "fix-parser",
    "base_sha": "<reviewed-existing-local-40-hex-commit>",
    "instruction": "Fix one preauthorized parser behavior",
    "target": "src/ai_foundation/parser.py",
    "test": "tests/test_parser.py",
    "test_sha256": "<64-hex-review-of-independent-test>",
    "source_sha256": "<64-hex-original-reviewed-source>",
    "model": "m1"
  }]
}

Ticket and source scope come from this owner-controlled file, never MCP
arguments. At most eight fixed one-file Python tickets are registered per
stdio host process. The host prepares an isolated local Git worktree from the
already-present reviewed commit without fetching GitHub. The existing Work
SQLite claim permits one attempt per ticket even after reconnection. A Guard
write and the existing fixed-test port must succeed to return VERIFIED_LOCAL.
The fixed source/test path, original SHA, worktree branch and current test
hash are checked; unknown or modified files fail closed.

## Model selection: public auto, M1-fixed private, observable fallback

The owner-controlled `model` field has three accepted values:
- `"auto"`: recommended for **reviewed PUBLIC_NONSECRET CODE** tickets. If
  MainPC Strata is configured, the exact authorized runtime model is currently
  online, the authorized bearer key is available, and the reviewed first prompt
  passes the local sensitive-input gate, use Strata for the first proposal. If
  unavailable or the reply cannot be accepted as Python, fall back to M1
  local-code-agent. Do not wake MainPC during inference.
- `"m1"`: fixed to the M1 local-code-agent even when Strata is online. Use
  for private/secret/HumanModel-bearing tasks and review/final acceptance;
  this is the existing default in older owner manifests.
- `"strata"`: legacy explicit Strata-first selection, still subject to the
  same public proof and M1 fallback as `"auto"`.

To authorize `"auto"` or `"strata"` for one reviewed PUBLIC_NONSECRET
source task, the owner must supply two additional hashes:
`public_source_sha256` equals `source_sha256`, and
`public_instruction_sha256` equals SHA256 of the exact UTF-8 instruction.
These are not signatures or automatic public classification; the trusted
owner must review the actual source/instruction before registering the ticket.
A caller cannot change the model or review scope through MCP arguments.
The outbound first prompt is pinned to the reviewed original source.
An altered prompt, changed source or sensitive input is not sent to Strata.
Repair attempts run only on M1; independent fixed acceptance remains on M1.
Missing optional endpoint/key or offline MainPC falls back to M1, **not** to
an unauthenticated endpoint or paid API. The existing 9B-only GitHub Issue
worker is a separate legacy path; this opt-in does not silently reroute its
unreviewed or owner-private requests to Windows.

A verified local receipt includes the actual selected model binding and source
SHA256; it does not leak private source, test logs or credentials. Receipt
does not imply GitHub delivery, main merge, M1 installation, or external
MCP-client E2E success. Those require separate release and independent readback.

The existing MainPC Strata preflight remains an explicit owner operation
rather than background wake or forced model restart. The host must separately
confirm direct LAN reachability, the real Strata runtime identity, and one
successful authorized public CODE task before treating MainPC as active.



## Existing 9B GitHub Issue worker: public-only Strata offload

The separate pre-existing `scripts/local9b_autodev_worker.py` now admits
`python-fixed-test` Issue contracts with `"model": "auto"` **only** when
`source_sha256`, `public_source_sha256` and
`public_instruction_sha256` are present and match the exact reviewed source
and instruction. This is a per-Issue host/owner approval, not a classifier
that can turn unknown/personal work into public work.

Before starting the resident M1 9B backend, the worker checks the already
installed `FOUNDATION_DATA_ROOT/local-compute/endpoints.json`, an actual
nonempty Strata API key, exact CODE model and online discovery. No automatic
MainPC wake, new listener or paid route is performed. If Strata is offline,
the original one-shot 9B implementation and M1 capacity/lease gates remain.
For explicit `"m1"` and legacy contracts without a model field, the old
M1 9B route is unchanged.

A matched public source and instruction are bounded to the existing 4,096
character public-prompt gate. The pinned independent test bytes and runtime
feedback **never** leave the M1; only the first candidate proposal is sent to
Strata. M1 executes the unchanged fixed acceptance and Guard write. Strata's
response is not allowed to select commands, files, tests, approval, branch
or provider. A remote inference result that was attempted is not silently
replayed as a second authorized Issue after an ambiguous delivery. Its
terminal receipt and Draft delivery status remain distinct. The legacy
Issue route still uses GitHub for intake and publishing; the direct MCP
development route above removes GitHub from the *inner edit/test loop*.

This is source code until the reviewed revision is installed and independently
verified on M1. Existing queued issues are never upgraded to external transfer
just because MainPC happens to be reachable.

## Separate GitHub delivery, never in the inner loop

By default, development_run and development_status cannot publish anything.
To allow one specified ticket to publish a Draft, the owner may add the exact
boolean field "allow_draft_delivery": true to that ticket in the protected
manifest. The separately scoped development_deliver(ticket_id) tool then
checks the already VERIFIED_LOCAL source hash and uses the existing
GitDraftPublisher. It does not rerun inference, regenerate source, or retest.

One SQLite Work claim guards each Draft delivery. A lost git push/create
acknowledgement remains RECONCILE_REQUIRED, not an invitation to retry the
remote side effect. Only an independently read-back Draft URL with the exact
branch/commit is stored as GitHub-published. This never merges main, deploys,
or claims CI passed. The same owner manifest and existing Guard are required.
After a Draft commit, a subsequent stdio host start accepts only the exact
one-file direct child commit of the reviewed base; no arbitrary HEAD advance.

The owner-local stdio tool catalog is opt-in as before. For an unapproved
ticket, a delivery call fails even if the authenticated session can discover
the tool. The project owner chooses whether Draft delivery is permitted
within the already admitted scope; model-generated content is never authority.


The immutable work contract (base/source/test SHA256, target, instruction,
model) is hashed into the existing Work step name. Reusing a ticket ID with
a changed contract rejects stale VERIFIED results. A later separately granted
allow_draft_delivery flag does not invalidate the tested source.


## Actual 2026-11-14 MainPC acceptance and activation (owner-measured)

Owner M1 observed directly (no GitHub runner inference): 8080 direct-LAN
unreachable, 18080 existing Windows portproxy reachable, Tailscale 8080
unreachable; 18080 `/v1/models` reports exactly
`qwen3.8-flash-next-coder-iq1_m`. A synthetic
`/v1/chat/completions` returned exactly `STRATA_ROUTE_OK` (real inference).
However `/health` said `api_key=false`; this is **not an
authenticated production Foundation route**. Evidence Issue #1040.

### One-shot, non-disruptive preparation (no main rewrite, no model restart)

From the existing owner Windows install only, run
`powershell -ExecutionPolicy Bypass -File scripts/mainpc_strata_stage_auth.ps1 -Stage`
if the file has first been brought to that machine from the reviewed
AI-Foundation release. This checks the known
`D:\\local-ai-probe\\Strata\\strata-coder-iq1_m.json`, adds a random 256-bit
`api_key` only if missing, creates a single pre-auth backup and copies the
secret to the Windows clipboard without printing it. It does not restart the
running server: `api_key=false` remains until a separately owner-controlled
normal Strata restart. Do not paste the key into ChatGPT/GitHub or disable the
M1-side authentication requirement.

On the M1, the local `main` branch has 43 divergent owner commits. Do not
reset/rebase/force merge it. Use an isolated `git worktree add --detach`
against newly fetched GitHub main and the pinned owner Operator `--config`
file; from that worktree execute:

```bash
python3 scripts/m1_strata_local_first_setup.py --config "$CONFIG" \
  --port 18080 --retarget-existing --apply
```

This changes only the reviewed MainPC base URL + matching host allowlist from
the historical 8080/Tailscale route to `10.0.1.1:18080`. It refuses
unrecognized model identity, scope, key binding, host, or optional flag. Other
local compute endpoints and installed services are untouched.

After Strata restarts *normally* under the staged authenticated config and
Windows `/health` reports `api_key=true`, use the same M1 owner worktree
to register a hidden-input key into the existing `ai-foundation` macOS
Keychain (account `local:mainpc-strata:api-key`):

```bash
python3 scripts/m1_strata_local_first_setup.py --config "$CONFIG" \
  --port 18080 --register-api-key
```

Registration first requires actual authenticated MainPC synthetic inference
`INFERENCE_VERIFIED` on the fixed private 18080 route. Only then is the key
saved; no secret is printed, sent to CI, stored in Git or passed as process
argv. The endpoint loader uses the existing STRATA_API_KEY environment
variable if present, else this **MainPC-only** native Keychain binding.
Other providers and endpoints cannot inherit it. An absent credential
remains optional/fail-closed. Do not infer credentials from an unauthenticated
health or runner's environment.

A real reviewed PUBLIC_NONSECRET CODE ticket via owner-local MCP is still a
separate acceptance step. Private HumanModel/source remains on same-host M1.
