# Foundation private MCP tunnel — first usable ChatGPT connector

**State: source setup + read-only M1 prerequisite check, NOT a live remote
connection.** This integrates the existing `foundation_status` stdio MCP
server; it does not modify Operator, Guard, KLM, Native or the single local 9B.
Kandev is neither launched nor relied on as a Foundation task executor.

## Connection

ChatGPT plugin → OpenAI Secure MCP Tunnel → outbound-only `tunnel-client`
on the owner M1 → **fixed Python launcher that removes inherited credentials** →
existing `scripts/foundation_mcp_stdio.py` → installed Operator loopback
`127.0.0.1:8766` → fixed aggregate `foundation_status`.

No new inbound public HTTPS service, extra MCP permission plane, copied Kandev
authorization, shared tunnel profile or arbitrary stdio command. The default
MCP tool catalog has exactly one read-only tool. The bounded owner-delegated
MCP with Guard actions, HumanModel and CODE tools is deliberately **not** this
remote entrypoint. Source tests or a tunnel doctor result alone cannot prove
a ChatGPT/other remote consumer was authenticated.

Official guidance: https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
and https://developers.openai.com/api/docs/guides/custom-mcp-server .

## One-time owner-local setup (only when the existing approved, no-paid-cost
Platform tunnel and restricted runtime credential are available)

The workflow neither generates new API credentials nor uses any paid model API.
**Do not create an unapproved billable Platform account, enable auto-recharge,
or activate this connection if its cost eligibility is unknown.** A
`tunnel-client` runtime control-plane API key may still be required by the
provider; it is not a Foundation model provider credential.

1. Install `tunnel-client` using the official supported macOS Homebrew
   package after owner review:

   ```bash
   brew install openai/tools/tunnel-client
   tunnel-client --version
   tunnel-client help quickstart
   ```

   Official project: https://github.com/openai/tunnel-client . Direct release
   ZIP files are not currently notarized; do **not** bypass Gatekeeper. Do
   **not** automatically install unverified downloads in a GitHub diagnostic.
   Use the exact opaque tunnel ID (including an optional four-character namespace) from Platform. Use an independent Foundation tunnel; do not reassign active Kandev
   endpoint. In ChatGPT web/Platform, confirm that the tunnel is associated
   with the intended ChatGPT workspace and has Tunnels Read + Use permission.
2. **Do not pull/rebase/reset** the owner's active
   `~/Develop/AI-Foundation` checkout. Source-only staging uses a dedicated
   one-shot owner Issue titled `Foundation M1 Tunnel Stage: source-only`,
   with the body shown below. It imports only the trusted event-time main
   commit into the existing owner Git object store, then adds an immutable
   worktree under `~/.ai-foundation-tunnel-sources/<exact-commit-sha>`.
   Existing branches, services, KLM, Guard and 9B remain unchanged.

   ```text
   <!-- foundation-m1-tunnel-stage:v1:source-only -->
   ```

   An official GitHub Actions bot receipt reporting `SOURCE_STAGED_VERIFIED`
   must be independently read before setup. The readiness probe prefers
   that versioned, source-matched private worktree; it never silently
   rewrites the owner's working branch. Run the CLI from the staged worktree
   rather than a transient GitHub runner checkout.
3. Through Keychain Access on the owner Mac, create a password item named
   `ai-foundation-tunnel-control-plane-runtime` holding **only** an
   independently approved, restricted tunnel-use runtime key. Do not paste
   keys into this chat, source, command arguments, GitHub, browser console,
   a persisted shell profile or a plist. The launcher looks it up through
   `/usr/bin/security find-generic-password`; a locked Keychain denies setup.
4. Execute from an **interactive owner M1 terminal**, not GitHub Actions,
   with no privileges beyond the owner:

   ```bash
   cd "$HOME/.ai-foundation-tunnel-sources/<exact-verified-main-sha>"
   /opt/homebrew/bin/python3.12 -B scripts/m1_foundation_tunnel.py status
   FOUNDATION_TUNNEL_ID='<exact tunnel ID from Platform>' \
     /opt/homebrew/bin/python3.12 -B scripts/m1_foundation_tunnel.py configure
   /opt/homebrew/bin/python3.12 -B scripts/m1_foundation_tunnel.py doctor
   /opt/homebrew/bin/python3.12 -B scripts/m1_foundation_tunnel.py run
   ```

   The last command is **foreground**, not a background service. It can be
   stopped normally from the same owner terminal. Neither `configure`
   nor `doctor` enables a production LaunchAgent, restarts Operator or
   sends a model request. Client stdout/stderr and key material are not
   relayed into Foundation reports. If the official client requires a
   different CLI contract, stop with `TUNNEL_CLIENT_OPERATION_UNVERIFIED`;
   validate exact installed client help rather than guessing new flags.
5. On ChatGPT **web**, open Plugins → **+** → Add custom MCP server →
   **Tunnel**, select the Foundation-only tunnel, review authentication,
   the risk warning and the discovered **single** `foundation_status`
   tool. This requires an explicit user installation action and supported
   account/workspace permission; a successfully configured local tunnel
   does not install the ChatGPT plugin itself.
6. Invoke `foundation_status` in a new ChatGPT conversation. Independently
   compare its aggregate output with Operator's current read-only view on M1,
   verify that all effect tools are absent and that the tool's session is
   associated with the intended client. Only then record
   `REMOTE_CLIENT_E2E_VERIFIED`. This has **not** happened by code merge.

### Read-only M1 prerequisite diagnostic

An exact owner-authored Issue titled
`Foundation M1 Bridge: tunnel-readiness` with body:

```text
<!-- foundation-m1-bridge: {"version":1,"operation":"tunnel-readiness"} -->
```

runs only source provenance and binary presence checks on the existing M1
GitHub bridge. No control-plane token, tunnel ID, process arguments, profile
content, private source or provider credentials are read or exported. Result
`READY_FOR_OWNER_SETUP` means prerequisites **only**, not a working
ChatGPT/Platform tunnel. `OWNER_SOURCE_INSTALL_REQUIRED` means no matching reviewed
source was staged or the private source is stale, or the user's original
checkout is still older; it does **not** mean that the running Operator is
stale. Use the one-time `Foundation M1 Tunnel Stage: source-only` request,
not `git reset` or branch checkout.

If direct ChatGPT plugin registration is not available in the user's account,
do not infer an outage in Foundation and do not create a public unauthenticated
HTTP endpoint. Continue via the already-supported GitHub connector or a
separately authenticated supported external AI client; the same read-only MCP
server remains usable locally.

## Authority and costs

- No external model or paid API, no automatic billing/credit usage.
- No permission copied from Kandev, GitHub or the model's clientInfo.
- A tunnel control-plane credential stays inside its own process. The fixed
  child `execve` drops `CONTROL_PLANE_API_KEY`, `GITHUB_TOKEN`,
  `OPENAI_API_KEY`, `FOUNDATION_TUNNEL_ID`, `PYTHONPATH` and every
  unlisted environment key before MCP executes.
- GitHub's read-only diagnostic cannot configure or start the tunnel.
- Actual authenticated remote tools beyond `foundation_status` require a
  separate owner identity proof, per-tool grants, and independent Guard policy,
  not a change to the exposure list in this file alone.
