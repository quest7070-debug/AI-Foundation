# 2026-11-03: original conversation export recovery and Raw Inbox read-back

Evidence grade: **direct private ChatGPT export** for the original conversation's text and message timestamps; **direct Automations latest_result** for the two current run receipts. This supersedes the earlier *missing original transcript* status for the period described below, without rewriting the older audit's historical state.

## Recovery scope and limitations

- Authorized private M1 external mount contains an official ChatGPT export dated 2026-11-01, with six `conversations-*.json` files. The original target conversation was matched by its exact conversation ID in `conversations-004.json`.
- The target conversation has **50 mapping nodes**, of which **49 have message objects, 40 contain text and 3 are user-authored text** over the full export window. The recovered target JSON is **4,398,188 UTF-8 bytes** and its SHA-256 is `a4c6797cf9883c2a808206e5389c10f4521597de42839d63ce7035194d6bfb18`. Full text and actual message IDs remain private.
- For **2026-10-09 through 2026-10-31 JST**, direct text was confirmed for **29 messages: 27 assistant and 2 user**. There are 9 additional non-text assistant/thought nodes in this date window; these are not counted as textual statements.
- **22 distinct days, Oct 9–30**, have substantive morning reports; Oct 22 has two adjacent report messages. **Oct 31 has only an automation error notice** in this export, not a successful opportunity report. No successful Oct 31 report may be invented.
- The two user messages in this gap are (a) an Oct 21 development continuation request, not acceptance of an opportunity, and (b) an Oct 30 request for a de-duplicated candidate list to be saved to Google Drive. The Oct 30 assistant explicitly reported **Google Drive not saved** and described a seven-page DOCX instead. The export proves the assistant's report, not independent existence of the DOCX or a Drive upload.
- Source message IDs and exact timestamps are recorded in a **private** index at `/Volumes/SubVolume/HumanModel/sources/chatgpt-export-2026-11-01/opportunity_message_index_20261103.json`. No message text, user wording, or message IDs are copied into this public repository.

## Corrected chronology (JST actual message timestamps, not report title dates)

| JST original message date | Directly observed leading topic / distinction |
|---|---|
| Oct 09 | FreeInference API; HybridInference; **Free Inference Directory is separate** |
| Oct 10 | Mellum2.1; Webcmd |
| Oct 11 | Agent test external-side-effect incident |
| Oct 12 | Hermes Agent Git side effects |
| Oct 13 | NVIDIA Kumo |
| Oct 14 | Clef-omni; Android TV distributed inference experiment |
| Oct 15 | MiniCPM-V / Lookahead Expert Scheduling |
| Oct 16 | LiteLLM dependency concern; Apple Minions |
| Oct 17 | speech.cpp; Industrial Edge RCS |
| Oct 18 | GitHub Actions Lockfiles; DXC OASIS |
| Oct 19 | Nemotron Bolt; PS5LM Plus |
| Oct 20 | Timestral; MiniMax M3.1 Flash |
| Oct 21 | OrcaRouter; Tev1; Reflection Beam; separate user development request |
| Oct 22 | LiteLLM supply-chain concern and separate OpenCode Console report (two messages) |
| Oct 23 | freehire; ALTK-Evolve |
| Oct 24 | FreeInference API reassessment; NTT method |
| Oct 25 | Microsoft 365 cross-tenant/agent security concern |
| Oct 26 | Decider for Mac; Recursive Flint |
| Oct 27 | Resonant; Containarium; Microsoft Scope |
| Oct 28 | **Bonsai 2 / 3060 Ti 8GB / 27B claim** — previously missed in secondary chronology; later speed claim retracted |
| Oct 29 | LFM3-Audio; Nemotron Super VL; Agent Reach |
| Oct 30 | GitHub Agentic Workflows and further comparison; separate user request and assistant candidate consolidation |
| Oct 31 | Error notice only; no substantive daily result |

**Correction:** The old `OPPORTUNITY_CHRONOLOGY_20261009_31_SECONDARY.md` rows were UTC-log/secondary labels, often one calendar day earlier than the directly observed JST message. They must **not** be used as authoritative JST dates. The October 28 Bonsai 2 report was omitted/misattributed in that secondary index. Its reported performance is an **AI assertion**, and the October 30 assistant explicitly retracted an unsupported 3060 Ti speed figure. Neither is a verified local benchmark.

## Decisions, candidate counts and provenance

- The Oct 30 assistant consolidation presents **6 prioritized + 6 conditional + 5 principles = 17 retained entries in that consolidation**. This is *not* the number of all unique historical discoveries, user approvals or installed tools. Other excluded items remain excluded from that 17-entry snapshot, not erased from Raw.
- Assistant `採用候補` wording throughout the daily reports is an AI classification, **not** user acceptance or implementation.
- New direct user adoption/installation evidence for the AI suggestions in the recovered gap: **0 confirmed**. Oct 30's request to produce a Drive document is an instruction, not acceptance of the listed technologies; the assistant reported that Drive upload was blocked.
- Oct 31's failure notice is an execution-status record, not a new opportunity.

## Raw-first storage receipts (private M1, 2026-11-03)

Three newly captured **source units** were ingested with the PR #81 local CLI into the mounted `/Volumes/SubVolume/HumanModel/sources/raw_inbox.sqlite3`: the original conversation export (`kind=chat`, `privacy=private`), the Nov 3 06:00 AI report, and the preceding Nov 2 07:00 recovery report (the latter two `kind=automation_report`, `privacy=restricted`). Distinct automation IDs and run revisions were preserved.

The database read-back returned **7 total Raw items, 0 reviews, `integrity_check=ok`**, and matching SHA-256 for each of the 3 newly stored content blobs. No source was truncated. **New Raw acquired 3 / saved 3 / newly acquired unsaved 0 / model reviews 0**.

The older Nov 1 06:00 automation **run-specific** payload is still unarchived because its run ID and complete Automations result cannot be re-read. The export now provides the corresponding day's conversation message text, but without a verified run-to-message identity join; do not pretend this resolves the run-specific provenance gap.

## Nov 3 daily run (direct Automation, not user approval)

Run `5c6e4c76-6148-8329-8bec-c73c5d9b8cd9`, completed Nov 3 06:06 JST, correct target conversation, `content_truncated=false`. AI proposed Lightpanda/PandaScript as a browser acquisition comparison and LLENS as an evaluation-method comparison; Agensh was rejected by the AI for overlapping execution responsibilities. **No user adoption or installed component is evidenced.** The prior recovery run `714e9a84-afb4-8330-bd8e-92fbdd410ff6` was also directly obtained and stored separately.

## Remaining work

- Reconcile private export message IDs with individual historic Automation run IDs only where an authorized direct run result exists; keep unknown run links unresolved.
- Validate the Oct 30 DOCX's existence and any later Drive save using original file/Drive evidence, not the assistant's promise.
- Compare the 17-entry Oct 30 snapshot against current Foundation/Concept OS implementation before any installation decision.
- Keep the audit pipeline and Raw Inbox separate from HumanModel Ledger; no auto-profile promotion, paid API, cloud model, or public private-text upload.
