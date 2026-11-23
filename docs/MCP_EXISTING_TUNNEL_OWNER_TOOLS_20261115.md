# Existing Foundation ChatGPT MCP connection: owner-Guard tool upgrade

**Connection count: one.** This is an opt-in replacement of the local
MCP command behind the already registered Foundation tunnel/profile, not a
second Secure MCP Tunnel, new tunnel ID, or new ChatGPT plugin.

The same original foundation-readonly profile and tunnel ID are used
because ChatGPT already successfully invoked foundation_status.
After switching, the new owner-bound MCP child continues advertising the
existing read-only status tool, alongside bounded Guard approval/development
tools. Private HumanModel source and arbitrary shell commands are not exposed.

## Fixed authority boundary

- Owner M1 uid 501, trusted source and Operator authority manifest required.
- Same existing Guard and Work SQLite stores; no second permission database.
- Each development tool accepts only a pre-registered owner-local ticket ID
  from the 0600 development/tickets.json manifest. Exact source/test hashes,
  scope and model restrictions stay on M1. development_run is one-shot.
- development_deliver requires separately authorized exact ticket opt-in,
  publishes Draft only, does not merge main and never reruns inference.
- Guard submit_decision requires an exact one-time owner-delegated request and
  the matching currently pending Guard ref; no client prompt can authorize it.
- The fixed stdio wrapper drops tunnel control-plane credential, GitHub tokens,
  Strata secrets, and unrelated environment before launching host tools.
  Any optional Strata or Draft delivery credential remains owner-controlled.
- The trusted MCP owner session reauthenticates on expiry. Fresh authority must
  match the original discovered tool catalog; no mid-session scope expansion.
- Old status-only script remains available for rollback. This changes only the
  explicitly opted-in local tunnel command, not its remote registration.

## One existing-profile switchover after PR acceptance and staging

The owner stops **only the existing foreground tunnel-client run** (never a
9B/Strata/Operator process). The official client supports one active stdio
instance per tunnel ID. Before switching, confirm owner source is staged and
owner's exact private development manifest/Guard permissions are ready.

From the reviewed, owner-installed source checkout on M1:

~~~~bash
/opt/homebrew/bin/python3.12 -B scripts/m1_guarded_tunnel.py status
/opt/homebrew/bin/python3.12 -B scripts/m1_guarded_tunnel.py configure
/opt/homebrew/bin/python3.12 -B scripts/m1_guarded_tunnel.py doctor
/opt/homebrew/bin/python3.12 -B scripts/m1_guarded_tunnel.py run
~~~~

configure uses tunnel-client init --force on the **existing** profile.
It reads the existing ID from the trusted owner local profile in
~/.config/tunnel-client/foundation-readonly.yaml (or the configured XDG/
profile directory); no new ID or key is created. It refuses an unknown
existing command, missing/ambiguous tunnel ID, or untrusted profile. It reuses
the already configured Keychain runtime credential and logs no secret or ID.
If the owner upgraded a custom profile by hand or used a different directory,
the helper fails closed rather than overwriting unrecognized settings.

If the remote tool catalog is cached, refresh/reconnect the **same existing**
ChatGPT connector. Do not register a second connector or tunnel.

After the switch, foundation_status must still return the current Operator
aggregate. Then verify one real external development_status(ticket_id) and
an explicitly owner-admitted development_run(ticket_id) with a matching
durable Work receipt. A doctor success alone proves neither remote
caller acceptance nor Guard/owner-answer execution.

If the upgraded child is unavailable, stop the new foreground process and
restore the original owner-verified m1_foundation_tunnel_stdio.py as
foundation-readonly's MCP command using the same existing tunnel ID with
tunnel-client init --force; then run its doctor and single client process.
Never run both processes with the same tunnel ID concurrently.

## Acceptance

Tests cover reused profile/ID, missing/custom/ambiguous profile refusal,
credential separation, owner-session renewal and scope expansion refusal.
One exact-head CI and one actual owner-host E2E are required; neither a new
tunnel registration nor additional model use is part of the code change.
