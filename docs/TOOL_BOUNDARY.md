# Tool / MCP execution boundary

Updated: 2026-09-18

ToolHive v0.49.0 is the current first implementation candidate behind the replaceable Tool/MCP execution boundary. It is Apache-2.0, ships darwin/arm64, runs MCP servers in containers, supports network isolation, audit configuration, OpenTelemetry and encrypted secret providers.

This is not a transfer of authority to ToolHive. Guard remains above it and owns Canon, Privacy, Authority/Approval, Budget and Effect/Verification semantics. ToolHive is containment/runtime plumbing below ExecutionPort.

## Security constraints
- Do not rely on MCP server output as authority.
- Bind each adapter to explicit host/container targets and reject path escape before calling MCP.
- Network isolation is desired by default. A clean M1 retest of ToolHive v0.49.0 with isolate-network enabled reached stable running state with DNS and egress helper containers healthy, and the live Guard/MCP E2E passed. Earlier restart evidence was contaminated by a prior malformed filesystem invocation and overlapping restart state; it is not evidence that isolation itself is broken. Production readiness still requires crash/restart and lifecycle automation.
- Keep Docker gateway access disabled unless a specific approved tool requires it.
- Secrets remain references resolved by a credential-bearing boundary; raw values do not enter Guard/TaskPlan/logs.
- ToolHive upstream security advisories must be checked before version adoption. ToolHive is defense-in-depth, not the Guard itself.

## Verified local probe
A registry filesystem MCP workload was mounted only to /tmp/ai-foundation-toolhive:/projects. ToolHive MCP write_file and read_text_file succeeded and host readback matched. ToolHiveFilesystemPort additionally rejects targets outside the configured mount. Guard -> ExecutionPort -> ToolHive -> MCP filesystem -> independent readback -> VERIFIED is covered by an integration test when the local ToolHive workload is available.

## Gate before wider use
Pin/verify server provenance where available, then extend lifecycle coverage to deterministic container-stop/restart timing before connecting an AgentPort. A deterministic local lifecycle script now ensures, stops, removes and reports the isolated filesystem workload; stopped-workload recreation is covered by live E2E. Path escape is tested at both adapter and MCP-server layers.

## Failure recovery verified
A live E2E simulates an MCP effect that succeeds in the filesystem but loses its response. Guard persists UNCERTAIN, the next attempt observes the real target through MCP, marks VERIFIED, and does not execute the effect a second time. This covers the critical ambiguous-completion contract at the ToolHive boundary.

A separate live E2E now kills the Guard process with SIGKILL immediately after the real MCP write. Durable state remains EXECUTING; after the claim expires, a replacement Guard observes the target through ToolHive and reaches VERIFIED without calling execute again. This verifies hard OS process death after the effect, not only a simulated lost response.

## Provenance and untrusted output
The current filesystem registry entry resolves to docker.io/mcp/filesystem:1.0.2. The running M1 container image ID observed on 2026-09-18 was sha256:720393842ef8b0f33713a42e2eebda51ff600756c19d53e1244645ec59496fef. ToolHive reports that this registry entry has no provenance metadata, so image verification is explicitly kept in warn mode rather than falsely claiming verified provenance. Production adoption must pin and verify an approved image source/digest or use registry provenance once available.

Tool output is data/evidence only. ToolObservation.trusted_as_authority defaults false and an adversarial-output regression test ensures strings that impersonate SYSTEM, Guard, canon or approval remain untrusted. No tool output may mutate Canon, approval, policy, budget or credential authority merely by text content.

The lifecycle now fail-closes before startup unless the locally resolved filesystem:1.0.2 image ID equals the approved digest sha256:720393842ef8b0f33713a42e2eebda51ff600756c19d53e1244645ec59496fef. ToolHive registry launch is retained because it supplies the required filesystem server arguments; direct digest launch was tested and rejected because it did not preserve registry configuration. This is digest pinning, not cryptographic publisher provenance.


## Reproducible CLI provisioning — 2026-09-24

The canonical M1 ToolHive executable remains repository-local at `.tools/toolhive/thv`; Foundation does not depend on a globally installed `thv` being present in the runner service PATH.

`scripts/bootstrap-toolhive.sh` now provisions that boundary deterministically for darwin/arm64 from the official ToolHive `v0.49.0` release. The bootstrap pins the release archive SHA-256 to `b78d8991cb6f3df35a543dd2456c8885ef7e34885517c62051c20443a7a711a0`, refuses another requested version, refuses a conflicting existing repository-local binary, and verifies the resulting executable reports the pinned version.

This closes a reproducibility gap discovered when the self-hosted Actions runner correctly checked out a clean repository: prior live ToolHive evidence depended on an untracked repository-local binary already being present. Existing filesystem lifecycle and new MCP backend probes must share this bootstrap contract rather than search arbitrary host PATH locations or install their own ToolHive copy.
