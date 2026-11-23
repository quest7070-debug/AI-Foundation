## About this repository

This is a sanitized public snapshot of the private AI-Foundation project (as of 2026-11-23). Hostnames, network addresses, local paths and document IDs in the original have been replaced with placeholders. Internal state logs are not included.

# AI Foundation

Fresh implementation of the generic AI/automation foundation.

**Current owner workflow (2026-11-13):** AI Foundation is primarily an authenticated MCP/API memory, development and execution substrate used from existing AI clients such as ChatGPT/Muse; LibreChat is optional. The *existing* Foundation Settings/Operator interface is being evolved in place into a one-page overview dashboard with Settings and Guard decisions retained. See [END_GOAL](docs/END_GOAL.md) and [Phase G](docs/PHASE_G_PLAN.md). This is the target architecture, not a claim that external MCP client E2E or the new overview is already live.

Concept OS is intentionally outside this repository and has no dependency on it.
Legacy MultiLLM, Automation Hub, AI Home Server and HumanConsole server authorities were migrated/retired through the staged Phase H cutover. M1Remote and Concept OS remain independent of AI Foundation. Historical migration records retain legacy names only as evidence.

Core rule: AI may propose how; deterministic guards decide whether execution is allowed and independent verification decides whether it succeeded.

## Operator tools for future development

ChatGPT/external-AI development operations use **M1 development bridge first, GitHub second, Desktop Commander last**, strictly within each tool's accepted capabilities. The M1 bridge accepts fixed `snapshot` / `selftest` operations and provides accepted `triage` for bounded read-only memory, service and process diagnostics (real M1 Issue #294). See [M1 development bridge and operator precedence](docs/M1_DEVELOPMENT_BRIDGE_20261107.md#operator-tool-selection-precedence--user-decision-2026-11-07) for fallback conditions, security limits, and evidence requirements.
