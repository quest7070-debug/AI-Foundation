# Source Relationship

Updated: 2026-11-22

## Authority

This GitHub repository (`quest7070-dev/AI-Foundation`) is the canonical source of truth for the current AI-Foundation implementation phase.

Canonical here means published specification, architecture, code, tests and recorded changes to AI-Foundation, in contrast to the historical Drive archive. The active development environment and execution owner are Foundation on M1, using its existing local Git checkouts and durable Work/Guard/effect evidence. A published GitHub revision is not proof of the currently installed runtime or the newest independently accepted local work. Local unexported results are preserved and reconciled, not overwritten merely because the remote has not caught up. GitHub is mainly record preservation; no mandatory remote Issue, PR, Actions, CI or live remote lookup for ordinary locally authorized development, repair or release. Existing exact authority and verification controls remain mandatory; migrate remote-dependent gates through a verified successor, never bypass them.

## Historical design archive

The preceding research and redesign history is preserved in Google Drive:

- Folder: `GPT用/AI基盤 OSS再構築_2026-09-17`
- Folder ID: `1T82IL9hV_lbbBOjR79JmMMYZiYsSXbI0`
- Entry document: `00_README_別チャット引継ぎ`
- Documents `00` through `09` preserve investigation, alternatives, PoC evidence, and the reasoning that led to this repository.

The Drive folder is an archive/reference, not a second current source of truth.

## Conflict rule

If GitHub and the Drive archive disagree about the current AI-Foundation specification or implementation, GitHub wins.

If the question is why a decision was made, consult the Drive archive for historical reasoning, then verify the current decision in GitHub before acting.

## Scope boundary

Concept OS is independent and outside AI-Foundation. Neither this repository nor the Drive relationship changes that boundary.

The legacy MultiLLM, Automation Hub, AI Home Server, HumanConsole, and M1Remote repositories remain historical/current references for their own existing implementations until responsibilities are deliberately migrated. They are not automatically made subordinate copies of AI-Foundation.

## Maintenance rule

Do not mirror ordinary implementation updates into Google Drive. Execute development locally on M1; preserve authorized source changes, outcome evidence and history in GitHub separately. If remote publication is temporarily unavailable, retain the exact local candidate and pending publication receipt, continue permitted independent local work, and reconcile publication idempotently without repeating execution or deployment. Keep the published-record versus actual-runtime distinction. Use Drive only when preserving material historical reasoning not appropriate in the repository.

The Drive entry document contains the reverse pointer back to this repository so either source can lead a future chat or maintainer to the other.