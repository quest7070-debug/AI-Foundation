# Google Drive information architecture and bounded reorganization — 2026-11-07

Status: **OPERATING PLAN / PARTIAL SAFE MOVES ONLY**. Technical implementation/specification is canonical in GitHub `docs/KNOWLEDGE_LIFECYCLE_MANAGEMENT.md`; Google Drive stores human-oriented plans, ToDo, inventory and audit snapshots. The historical Drive `GPT用/AI基盤 OSS再構築_2026-09-17` is not a second technical canonical spec.

## Verified top-level folders / canonical entry points

- `My Drive/ChatGPT` (id `1STI50E4T3CXMsEHA1XXisptUPNuOhXgV`): current operational entry point.
  - Existing `00_START_HERE｜Drive・人間モデル・ToDo運用入口` doc: id `1Yp3QRvb5TZ4PT8NCQtui0rAHGOXKclAHyBPWjZHIcTk` — do not rename or move.
  - Existing `統合ToDo台帳｜人生・プロジェクト・実行管理｜2026-10` spreadsheet: id `12Vuz-C0YtcM9iDSriAUC_s5jtQ1Kt6pB6k70fzlYKu0` — retain existing URL and tabs.
  - `01_思考と人間モデル` (id `1NLlrz33t1PtW4OJc_0QoU-PR5-OBxhza`): **human-readable derived proposals/reference only**; HumanModel SQLite is authoritative for approved person evidence.
  - `02_横断計画と意思決定` (id `13eAX0F_u-iAUp8kxLymhL2n5WKnpXYeT`): operational cross-project planning.
  - `03_資料アーカイブ候補` (id `1jn5i6oQhhk1A0tt6giU5I3Y7cWQ_3ne2`): explicit archival candidates; no automated deletion.
  - `04_監査と変更記録` (id `1_KzbaaqCQBcLklBI1CJ3yn10zhQb5wbs`): audit snapshots, index discrepancies, move receipts.
  - `05_知識ライフサイクル管理`: proposed/created on 2026-11-07 for operator-readable KLM plan, placement matrix, progress, and audit results. New folder is NOT a competing truth store.
- `My Drive/GPT用` (id `1Uy2jX_FYY12LLx0Qblj1csEzKnNcq6r7`): older or specialist AI references; separate historical material from current operator entry. Existing folders `AI基盤 OSS再構築_2026-09-17`, `環境・システム全体資料`, `GPT-Muse-Foundation-Bridge`, `整理済み`, `人間メモ`, `アウトプット` remain intact and retain their exact IDs.
- `My Drive/転職計画` (id `1pV2eTM5RjOzBHCN4KuWQP2OTcmatp_xo`): current career master, job applications, resume variants and job listing audit; preserve native document IDs.
- `My Drive/PC資産` (id `1VyYV3_OFsf-8bHPFxfEVog7BCFkyDqhi`): inventories and machine records; one `台帳` child folder.
- `My Drive/サウンド` (id `19Godg2WC-TsmsV8e2ciXP3L4EGVG8OIB`): music projects, audio assets and directly relevant related research.
- Root `アカウント台帳`, device wallpaper and other uncertain-purpose files: keep unchanged pending ownership/usage inspection; avoid sweeping moves by title alone.

## Current gaps from bounded inspection

1. `ChatGPT/01_思考と人間モデル` and `ChatGPT/04_監査と変更記録` were empty when inspected; the audit snapshot `AI-Foundation 三面照合監査 2026-11-04` resided at root.
2. Current `ChatGPT/00_START_HERE` + ToDo spreadsheet are the operational entry; do **not** move them into the new KLM folder or replace them with KLM documents.
3. Old AI architecture docs remain under `GPT用/AI基盤 OSS再構築_2026-09-17`; relocating those history files to a new technical Canon location would risk authority confusion.
4. Material under `転職計画`, `PC資産`, `サウンド` is subject-specific; KLM stores *references* to these, not duplicate copies.
5. The Drive `人間モデル` tab is a human-maintained planning/provisional summary; not identical to HumanModel external-SSD original SQLite evidence and approval state.
6. Google Drive nested folder listing alone is not evidence of global inventory completeness; maintain per-folder traversal checkpoints.

## Placement policy: no scope widening

- **KLM specifications, source contracts, OSS version decisions, code and tests** → GitHub review/PR, never historic Drive archive as competing Canon.
- **Cross-project tasks** → existing `統合ToDo台帳` and appropriate owner task stores.
- **Personal explicit judgments and reasons** → HumanModel owner-approved original evidence; Drive records only contextual task/planning projections with source reference.
- **Audit findings and migration logs** → `ChatGPT/04_監査と変更記録`, links back to GitHub evidence; avoid personal Raw replication.
- **Current KLM operator explanation and folder map** → `ChatGPT/05_知識ライフサイクル管理`.
- **Legacy architecture debates** → preserve `GPT用/AI基盤 OSS再構築_2026-09-17` without silent promotion.
- **Ambiguous files** → no move, mark review candidate with original ID/path and reason.

## Safe reorganization procedure

A move preserves file ID and document contents but may affect access/parent inheritance, traversal-based automation and folder-link references. Therefore:
1. Ground exact file ID and verify current parent(s) and destination folder ID; check sharing/ownership and current users/integrations.
2. Move only uniquely classified current-operational files, no bulk title-based migration. Record before: file ID, old parents, target parent, motive, time, effect approval.
3. Call Drive move preserving all unrelated parent memberships, then independently read back exact file ID + target parent. If result uncertain, inspect current state before retrying.
4. Existing shared, secret-bearing, personal Raw or active pipeline files default to NO_MOVE.
5. Keep the original direct file URL unchanged; update human navigation documents and indexes only after verified move. No duplicates, renames, deletions or permission changes as part of cleanup.
6. To replace a person judgment or change technical canonical source, use the originating owner's explicit review process, not file movement.

## Proposed change set

- Create `ChatGPT/05_知識ライフサイクル管理`.
- Create one user-oriented design + folder policy document there, linking this GitHub contract and existing live ToDo/entry.
- Move only `AI-Foundation 三面照合監査 2026-11-04` (root) to existing `ChatGPT/04_監査と変更記録` after exact-parent/readback verification.
- Optional `11月6日以降の新着無料DTMツール（期限順）` (root) → `サウンド`, only if its existing reference/move effect is explicitly grounded; otherwise leave.
- Keep all other inspected files in place pending complete inventory and source-owner reconciliation.

## Future fuller layout (optional; do not create redundant empty folders now)

- `ChatGPT/05_知識ライフサイクル管理/01_方針と配置規則`
- `ChatGPT/05_知識ライフサイクル管理/02_棚卸・不整合`
- `ChatGPT/05_知識ライフサイクル管理/03_再配置・修復履歴`

Create these **only when their contents and users justify them**; folder depth does not itself improve correctness. Existing `01`–`04` ChatGPT folders stay current.

## Acceptance

- All changes are enumerated with exact IDs and independent readback.
- Operational entry doc and consolidated ToDo remain at their existing IDs.
- No historical AI Drive memo is elevated to GitHub technical Canon.
- No Raw personal original, shared permissions or source-owner state is implicitly changed.
- Read-only inventory reveals duplicates and ambiguous cases before any more moves.


## Executed organization receipts — 2026-11-07

The following changes are **actually applied and independently read back**; this section supersedes their earlier proposed/pending status in this document:

| Result | Exact resource | Verified parent |
|---|---|---|
| Created KLM folder | `1akJ7VtJY6BEvF4qugFFnI5j0UYnfGpo-` | `ChatGPT` (`1STI50E4T3CXMsEHA1XXisptUPNuOhXgV`) |
| Created KLM operator Doc | [KLM運用方針](https://docs.google.com/document/d/1AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/edit), id `1AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA` | KLM folder `1akJ7VtJY6BEvF4qugFFnI5j0UYnfGpo-` |
| Moved 2026-11-04 AI-Foundation audit snapshot | id `1yOP8yzxL8HOU68x7MbUbICsGRGjRLJCp4KSEyuAIXSc` | `ChatGPT/04_監査と変更記録` (`1_KzbaaqCQBcLklBI1CJ3yn10zhQb5wbs`) |
| Moved new free-DTM-tools Doc | id `1xgEmMsowjSy75OEa_QfO6OIwxo-pi8pSxjNmf1wALv4` | `サウンド` (`19Godg2WC-TsmsV8e2ciXP3L4EGVG8OIB`) |

For both moves the source parent was My Drive root `0AMsIyN5r239VUk9PVA`; the destination file IDs were unchanged. Verified each target-folder listing after update. No delete, rename, duplicate, or sharing mutation requested.

The existing `ChatGPT/00_START_HERE` Doc was appended (revision-guarded) with links to [Draft PR #277](https://github.com/quest7070-dev/AI-Foundation/pull/277), [Issue #278](https://github.com/quest7070-dev/AI-Foundation/issues/278), and KLM folder/Doc. Existing ToDo spreadsheet `12Vuz-C0YtcM9iDSriAUC_s5jtQ1Kt6pB6k70fzlYKu0` received **P17**, **T08**, index rows 19–20, inventory rows 96–99, and change-history rows 45–47. These exact ranges were independently read back; existing P01/technical runtime rows were left unchanged.

Unmoved: the root account ledger, wallpaper and any unknown/shared/personal original; all historical `GPT用` architecture documents. Remaining work: a complete paginated Drive inventory and links/permission-aware reorganization proposals, rather than bulk automatic moves.
