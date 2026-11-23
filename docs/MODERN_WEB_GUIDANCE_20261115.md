# Modern Web Guidance 1.0 — on-demand host integration

Source: https://github.com/GoogleChrome/modern-web-guidance
Pinned public npm package: `modern-web-guidance@1.0.0` (Node >=22).

## Scope and ownership

Foundation Guard/Harness retains source identity, privacy classification, model
routing, grants, tests and publication. This integration adds **only** an
optional local, read-only browser-platform reference in the existing
`AutoCapabilityAgent` with a trusted repository CODE capability. It does not
create a daemon, scheduler, paid API, WebMCP server, installation side effect,
or new approval/workflow. Ordinary CHAT and HumanModel paths do not get it.

When the verified CLI is installed in `/opt/homebrew/bin/` or
`/usr/local/bin/`, a CODE-capable agent receives `web_guidance(topic)`. It
selects one of the fixed, generic public topics declared in the tool's
docstring and retrieves one locally indexed guide. The tool is optional:
missing/mismatched package, malformed search, timeout or CLI failure returns
an explicit unavailable status. No package download occurs in the call.

The owner-local Strata direct-development route additionally supports **opt-in**
guidance for the existing HTML-rendering Python modules
`src/ai_foundation/operator_server.py` and
`src/ai_foundation/human_renderer.py`. A trusted owner manifest must
declare `web_guidance_topic` from the fixed public allowlist **and** meet all
existing public source/instruction SHA checks, along with a reviewed independent
Python test. The trusted host retrieves a guide once *before* constructing the
initial prompt and computing the Strata prompt SHA. The same exact enhanced
instruction is passed to the model, so no runtime prompt modification bypasses
the original binding check. If the reference is absent or exceeds the existing
4,000-character instruction limit, the original reviewed task runs unchanged.
No arbitrary prompt, private input or file path is used as a search query.

This is a prepared integration path, not proof the CLI is installed on M1 or
that a real Strata Web-UI task was run. DSH/OpenCode/Codex OSS retain their
current execution contracts and do not automatically consume this guide.

## M1 installation/acceptance (owner CLI installed; external frontend E2E pending)

The existing scoped M1 Runner accepted the global v1.0.0 installation with a real
search/retrieve (run 43659425285 SUCCESS; no model calls). The following is a
manual fallback recipe, not a prerequisite to repeat the successful install:

```sh
export DISABLE_TELEMETRY=1
npm install --global modern-web-guidance@1.0.0 --ignore-scripts --no-audit --no-fund
modern-web-guidance search "animate a dialog modal backdrop"
modern-web-guidance retrieve "animate-to-from-top-layer"
```

The last ID is the upstream README's example. In production, retrieve only
an ID actually returned by `search`. The actual Foundation tool validates the pinned npm
package identity, blocks network egress with the existing macOS
`sandbox-exec`, uses a fresh temporary HOME, clears secrets from the
subprocess environment, and bounds output and elapsed time. It NEVER forwards
request text/source or uses `npx @latest`.

The guide itself is untrusted reference data: it cannot grant tools,
override project Canon/Guard, set browser support policy, authorize a model
or alter production behavior. For a web-CODE task, compare the returned
guidance to actual target browsers and independent acceptance tests; if the
adapter is unavailable, keep the original development path.

## Minimum proof

```sh
python -m pytest -q tests/test_modern_web_guidance.py
```

Acceptance stages remain separate:

1. Source/CI: exact-current-main reconciled unit tests and code review of the new Draft PR.
2. M1: pinned installation, one live `search` + `retrieve`, then one
   authorized frontend CODE call using the guide.
3. Strata: a trusted owner-reviewed Web-renderer Python ticket with
   `web_guidance_topic`, source/instruction hashes and independent fixed
   acceptance. The fake-Strata offline test verifies hash parity but does
   **not** replace the real M1/Strata model E2E.
4. DSH/OpenCode/Codex OSS: their own optional guide-bound prompt contracts
   still require a separate review and real acceptance.
