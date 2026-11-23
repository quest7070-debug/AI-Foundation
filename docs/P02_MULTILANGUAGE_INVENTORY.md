# P02 — Multi-language inventory and explainability gate

## Purpose

Close the Python-only inventory gap without adding a Foundation-owned parser or
a second repository graph. The inventory is derived evidence; it does not
create Canon meaning, execution authority, or approval.

## Backend ownership

- Infigraph 3.2.16 owns repository-wide file/symbol indexing for its declared
  language packs, including JavaScript/TypeScript, shell and native languages.
- LibCST 1.9.0 remains the narrow owner of Python (.py and .pyi) scoped
  variables, reads and writes.
- CompositeCodeIntelligence combines Infigraph's multi-language symbol
  inventory with LibCST's Python scope inventory. Python structural fallback
  remains visible if LibCST cannot complete.
- Foundation translates these observations into the existing
  CodeIntelligencePort and SemanticCoverageRecord contracts only.

## Implemented in this slice

1. Infigraph INVENTORY queries its File and Symbol graph tables.
2. Supported extensions are read from the pinned Infigraph language registry;
   source paths are enumerated from Git.
3. Configuration/build manifests and generated/native artifact extensions are
   explicitly included in the expected path set. A path absent from the index
   is retained as a file-level inventory record and listed in
   failed_files.
4. Unclassified tracked paths are not silently omitted: known documentation
   and media assets are excluded, while unknown file types become explicit
   file-level gaps. Symbol-count mismatches and malformed rows are unresolved
   observations, not silently dropped results.
5. Partial semantic coverage retains observed records while reporting
   UNKNOWN. Explicit Canon declarations still require a fresh, complete
   inventory before they can be accepted.
6. The M1 audit downloads the official Infigraph 3.2.16 ARM64 macOS release,
   verifies its published SHA-256 digest, and writes only a derived local index
   plus a private receipt outside the worktree. No workflow artifact is
   uploaded.

## Real M1 inventory evidence — 2026-11-12

The exact-head P02 [M1 inventory run #43238578245](https://github.com/quest7070-dev/AI-Foundation/actions/runs/43238578245)
completed successfully after PR #764 isolated Infigraph-generated root
`tsconfig.json` and PR #769 taught the existing configuration inventory to
account for previously unknown Dockerfile, `.command` and archived evidence
`.log` paths without reading or interpreting their payloads.

- Fixed regression tests: **121 passed**.
- Backend: **Infigraph 3.2.16 + LibCST 1.9.0**; fresh index receipt.
- **918 expected** files; **861 backend-analyzed** plus **57 explicitly
  accounted structural fallback** files.
- **23,432 source-derived inventory records**, **0 unaccounted files** and
  **0 unresolved inventory observations**.
- `inventory_complete=true` means every expected file is accounted for at
  least structurally; the full analysis result is **`PARTIAL`**, not
  semantically complete or Safe-Change approved. The 57 fallback paths are
  still listed as backend `failed_files` because they were not structurally
  indexed by Infigraph, even though the configuration fallback records them.
- This is one reproducible source/CI observation, **not proof** that the
  installed production worker switched to this commit or that the symbols'
  intended meaning, external effects and test mappings are understood.

This supersedes the earlier P02 task of merely running a first real M1
inventory. Preserve the next work as *semantic* and source-to-test mapping,
not more broad reindexing or a second parser.

## What this does not prove

- A symbol's purpose, rationale, ownership, side effects or invariant.
- That every configuration key, generated file, binary, native artifact or
  build-time transformation has been semantically explained.
- That unresolved/dynamic/external calls are absent. Infigraph-resolved
  CALLS edges remain only observed edges; unresolved targets stay UNKNOWN.
- That every symbol has a deterministic test/evidence link.
- That a code change is safe to execute or merge.

The audit may report PARTIAL and still complete successfully as a diagnostic.
That is not a green explainability gate. The gate remains blocked until all
relevant paths are accounted for and the semantic obligations are explicitly
grounded.

## Remaining P02 work

1. Use the **completed real M1 inventory** above to review the 57 structural
   fallback paths and semantic completeness. There are no unknown expected
   files in this snapshot, but fallback inclusion is not semantic acceptance.
2. Add explicit per-symbol semantic declarations for relevant non-Python
   functions, methods, constants and configuration boundaries. Do not infer
   purpose from names or comments.
3. Link generated/native artifacts to their exact generator, source inputs,
   build command, digest and consumer boundary.
4. Represent unresolved dynamic dispatch, shell/process invocation, FFI,
   provider/network effects and configuration-driven targets explicitly.
5. Require deterministic affected-test and provenance links for each relevant
   changed symbol; reject unmapped relevant changes in the Safe Change preflight.

## Safety boundary

This P02 inventory is diagnostic evidence only. It does not execute development
tasks, authorize effects, alter source files or bypass Foundation Guard.
Current development ownership is defined by `SYSTEM_ROLE_BOUNDARIES.md`:
GitHub owns Issues/PRs/CI identity; Foundation host/Guard/Harness own admitted
scope and roles; existing bounded worker and optional DSH→OpenCode / Codex OSS
frontends execute only admitted work. Historical Paseo/Kandev routes are not
mandatory default task, worktree or execution owners.
