# General-file discovery through the existing MCP boundary

## Behavior

An Agent with an explicit host-selected general file read root can now call
`list_files(target='.')`, select a name from that observation, then call the
existing `files(target)` reader. A structured-data task can continue to the
existing bounded DATA operation within the same Pydantic AI tool loop.

Previously FILES exposed only reads of already-known paths. No custom file
search engine, index, parser, storage layer or second Agent is introduced.
ToolHive's already-selected filesystem workload owns directory enumeration.

## Authority and compatibility

- Only a general file read root enables the tool. Repository scope, an ordinary
  chat, and attachment mode do not grant directory discovery. Attachment mode
  keeps its existing single verified-attachment read behavior, including when
  a general root is also configured; it must not silently read an attachment
  when the Agent intends to read a discovered general file.
- `file_operation` is a host-built CapabilityRequest field, defaulting to
  `read`. The model sees only `target`; it cannot select owner, root, server,
  mount, arbitrary MCP tool, recursion, write authority or result-size limit.
  Existing read targets are still literal paths, including JSON-looking names.
- FILES dispatch reuses `ScopedFileExecution` and its resolved ReadCapability.
  Traversal and symlinks escaping that root fail before port invocation.
  ToolHiveFilesystemPort independently enforces its mounted root and calls only
  MCP `list_directory` with the translated path. Subsequent file reads recheck
  their own target; a name returned in a listing grants no new authority.
- Directory discovery is observational: no Guard Effect, reconciliation recipe,
  write, credential change, directory creation, service restart or model call.
  Existing activity/tracing surrounds the FILES call without recording contents.
- The MCP response must contain bounded valid text and no error flag. More than
  32 KiB of UTF-8 listing text is rejected, without presenting a truncated list
  as complete. The existing subprocess timeout remains 30 seconds. This bounds
  Agent-visible text, not the upstream server's enumeration or subprocess output
  capture. Large directories require a narrower host-approved directory; no
  pagination or recursive completeness is inferred.
- Listing text remains untrusted evidence. It is not parsed into authoritative
  paths or instructions. Filenames containing newlines retain upstream textual
  ambiguity; a requested read still requires a valid scoped target. No stronger
  race/TOCTOU guarantee than the existing host/MCP read boundary is claimed.

## Source relationship and acceptance

Based directly on canonical main `6bd2d7982f4480a1eb6bab054a09cb2e8beda2e9`.
The existing pinned workload remains `docker.io/mcp/filesystem:1.0.2` with the
unchanged digest in `scripts/toolhive-filesystem.sh`.

The upstream tool contract was checked against
[`modelcontextprotocol/servers` at `194cc86e`](https://github.com/modelcontextprotocol/servers/blob/194cc86e3ae6400958555bd4116849d822d69263/src/filesystem/server.ts#L518):
`list_directory(path)` returns nonrecursive `[FILE]` / `[DIR]` text under MCP
`content`. This current upstream source check is not proof of the installed
image's exact package revision; the isolated tests verify the adapter's exchange
contract. Live workload acceptance remains separate from source/fixture CI.

Focused tests cover the real Pydantic AI list -> read -> DATA loop with a fixture
MCP exchange, fixed CLI arguments, scope and mount denials, attachment-mode
denial, no Effects, malformed/error responses, UTF-8 output bounds and empty
directories. Tests make no real inference/provider calls.

This is an independent source-only feature slice. It shares narrow Agent/FILES
files with draft artifact PR #179; reconcile both diffs before joint promotion.
It does not include #179's write feature or the backup/monitoring changes in
#181/#182. No LibreChat integration, production activation, paid provider, model
download, Native dispatch, main merge or Desktop Commander is part of this work.

## Existing and isolated workload acceptance

`tests/test_file_listing_live.py` contains separate opt-in M1 gates. The initial
existing-workload observation in [run #41813499517](https://github.com/quest7070-dev/AI-Foundation/actions/runs/41813499517)
found `ai-foundation-fs` **unhealthy**: its state file said running while the
runtime reported stopped. It failed before fixture creation. The production
workload was not restarted, reconfigured or accepted as healthy.

The PR183-specific CI step therefore verifies the feature using a separately
named disposable ToolHive workload, never the production name. It bootstraps the
existing checksum-pinned CLI in the checkout, requires the already-present pinned
filesystem image ID, and starts only that image's immutable registry digest.
ToolHive owns its stdio/streamable-HTTP proxy, network isolation and lifecycle.
Its only explicit fixture bind is read-only and lives under RUNNER_TEMP.

Both gates verify image identity and the selected mount before the tool loop.
A deterministic Pydantic AI model selects tools while the real ToolHive/MCP
supplies listing and file contents; all external inference is disabled. Only
synthetic data is created and the Agent receives the `allowed` child scope.

Acceptance requires actual list -> read -> DATA readback (mean 7), an actual
empty-directory observation, traversal/symlink denials before MCP, zero Guard
Effects and removal of only the owned synthetic fixture. Public evidence is
bounded status/count metadata. The isolated gate also verifies the read-only
bind and network-isolation label. Cleanup removes only its own unique workload
and fixture and fails if the owned container remains. Missing prerequisites
never trigger image/model downloads or production lifecycle changes. Live
results belong to the exact GitHub Actions head/run recorded in PR #183; test
presence alone is not acceptance. Isolated success cannot establish production
workload availability or user-facing activation.
