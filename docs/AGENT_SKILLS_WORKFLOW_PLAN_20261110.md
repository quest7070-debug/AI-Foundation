# Agent Skills・業務ワークフロー再利用計画 — KEITOエコシステム比較（2026-11-10 JST）

**状態：調査済み・実装計画のみ（PROPOSED / NOT DEPLOYED）**  
**正本：** `quest7070-dev/AI-Foundation` GitHub。本文は既存Canonに対する具体的な機能追加候補であり、権限委譲・実装・有効化・mainマージ・実機受入を意味しない。  
**スコープ：** 汎用AI業務スキルの発見、手順の再利用、限定された組み合わせ、成果物検証、実績に基づく改善候補化。新しい司令塔や開発OSを作らない。

## 0. 調査対象・証拠と限界

### 観測した構造（2026-11-10時点）

2026-11-05のKEITO氏による図の公開と、2026-11-07の解説動画「AIガチ勢のAI環境を徹底解説！」を起点とする。ユーザー提供図に見える入口（Claude Code／Discord／スマホ／定期処理）、ハーネス、スキル、MCP/API、外部アプリ、結果の流れを参考にした。

- KEITO氏の公開発信・動画索引：[本人の公開投稿](https://teapaw.org/keitowebai)、[動画一覧](https://yutura.net/channel/85090/latest/)、[元動画](https://www.youtube.com/watch?v=8XbqxjJOP08)。
- 動画の二次要約：[AI Daily Digest（2026-11-07）](https://ai-daily-digest.com/news/c0bcac69-f26b-454b-9fff-a118e25bd440)。ブログ、広告動画、請求書などの具体的業務、Obsidian、スキル、MCP、判断レイヤーの説明あり。**動画をAIが要約し運営者が確認した二次情報**である。細部・「150以上」・「Jev 0.2〜0.35秒」・品質/速度の再現性はコードと独立実測で検証しておらず、性能要件・採用根拠にしない。
- KEITO氏の個別スキル活用例：[エージェントスキル10選の紹介](https://sac.epoch-inc.jp/works/keito-d3ftx4kjlyw/)、[Obsidian連携の紹介](https://sac.epoch-inc.jp/works/keito-tu8dsyumto4/)。第三者解説／制作資料であり、エコシステムのソースコードやセキュリティ監査ではない。
- Agent Skillsの一次仕様：[Agent Skills Specification](https://agentskills.io/specification)：必須`SKILL.md`、YAML frontmatter `name` / `description`、任意`scripts/`、`references/`、`assets/`、段階的読み込み。実験的`allowed-tools`は**権限証明ではない**。
- MCP側一次仕様：[MCP Skills Extension](https://skills.extensions.modelcontextprotocol.io/)：`skills/list`・`skills/get`・`resources/read`、宣言されたcapabilityと検証されたskill-loading。通常の資源読込はスキルの有効化／承認ではない。
- 権限の一次説明：[MCP Tool Annotations as Risk Vocabulary](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/)：`readOnlyHint`などの注釈は強制的隔離でも注入防御でもない。

### Foundationの既存正本（新設より優先）

| 所有者・正本 | 既にある責務 | 本計画で追加してはならない重複 |
| --- | --- | --- |
| `docs/END_GOAL.md` | LibreChat → Foundation Agentの**一つのAgent/tool loop**、host-authorized tools、日常E2E | 追加のユーザー向けモード選別、前段の汎用意図分類器、第2司令塔 |
| `docs/SYSTEM_ROLE_BOUNDARIES.md` | FoundationはCanon/Guard/Privacy/能力・検証、開発ライフサイクルはKandev | 第2の開発ワーカー管理、worktree/セッション/依存グラフの正本 |
| `docs/BOUNDARIES.md`、`docs/DEVELOPMENT_APPROVAL_IMPLEMENTATION_20261108.md` | 権限・承認・Credential/ExecutionPort・LV1〜LV5、外部効果の検証 | Skill自体の承認権、独立承認DB、任意shell/ファイル/認証拡張 |
| `docs/KNOWLEDGE_LIFECYCLE_MANAGEMENT.md`、`docs/KLM_READONLY_CORE_20261107.md` | 事実の出典・版・意味・所有者別配置・独立読戻し | 第2記憶DB、第三者文書からCanon/人格判断への無断昇格 |
| `docs/HUMAN_ESCALATION_POLICY_2026-10-06.md` | HumanModelは例外的価値判断の既存根拠参照、決裁はGuard | 「判断AI」を常時挿入、AIによる追加権限の付与 |
| `docs/GITHUB_AUTO_DEVELOPMENT.md`、`docs/NON_SELFDEV_BACKLOG_20261102.md` | 開発候補の発見・限定実行契約、既存業務適用待ち | 独立Issueキュー、全機能を自律開発へ誤接続 |

**差分の結論：** 追加余地は「仕事のやり方（可搬型Skill）のソース、選択・適用・検証インターフェース、実績に基づく改善提案」。実行権限、ジョブ管理、一般的ツール選択、記憶・ルーティングは既存所有者に留める。

## 1. 採用する構造（最小）

```text
Human / existing automation / existing task
  → one existing daily Agent / host-provided limited tool inventory
  → optional Skill discovery (metadata only) → on-demand selected SKILL.md
  → existing host permission & Guard preflight (task, scope, privacy, budget, effect)
  → existing ExecutionPort / MCP adapter / local or admitted free model
  → independently verified artifact / real-world readback / effect receipt
  → existing KLM source links and bounded improvement proposal
```

- **Skill** = 再利用する作業手順、前提条件、成果物の形式、失敗時の扱い。外部APIへのアクセス権ではない。
- **Tool/MCP** = 実際の限定された操作能力。Hostが本人・現行権限に応じ公開する。Skill本文やMCPメタデータは権限を増やさない。
- **Workflow** = 既存Agentが必要に応じ複数スキルを適用するタスクの実行。複雑/耐久性が必要なら既存Durable Work等へ委譲する。新しい常設実行管理を作らない。
- **Evidence** = 元入力の版・利用スキルのハッシュ・限定された操作・出力・独立検証結果。元の所有者が正本、KLMはリンク/索引/候補。

### Skill互換と追加のhost-envelope

ソース形式はAgent Skillsを優先する。例：

```text
<canonical-skill-root>/<skill-id>/
  SKILL.md                 # standard name / description + human instructions
  references/              # optional, only when invoked
  scripts/                 # optional, never executed just because present
  assets/                  # optional, templates/public fixtures
```

**正本ディレクトリは既存Agent/CLIのスキル探索規約の実コード調査後に1つ選定する。** 初期計画では`.agents/skills`等を勝手に正本化しない。Claude、Codex、OpenCode等の個別互換が必要なら、複製ではなくアダプター／参照を使う。

別途hostが管理する**検証可能な付帯情報（Skill本文を根拠としない）**に、少なくとも以下を持つ：`source_origin`、`source_commit_or_digest`、`license`、`owner`、`trust_class`、`supported_surface`、`declared_inputs`、`declared_outputs`、`fixture_ref`、`verification_rule`、`external_effects_requested`、`privacy_requirements`、`tool_dependencies`、`runtime_constraints`。既存コードに同等契約があれば再利用し、独立した永続スキルDBは作らない。仕様上の`allowed-tools`を権限に昇格させない。

## 2. 導入順（Gateと成果物）

### P0: 構成棚卸・重複排除（読取専用）

1. 現行Agent/tool-loop、スキル／プロンプト定義、ToolHive/MCP adapter、開発スキル関連、KLM source links、Guard preflightを実コードで確認。
2. 見つかった共通手順を`reusable skill` / `existing tool` / `existing durable workflow` / `owner-specific rule`へ分類。名前違いの二重実装をしない。
3. 既存機能で実現できる内容を除去し、**追加変更ファイルと呼出点**を具体化してから着手。

**合格:** 既存所有者と参照パスが特定され、追加しない機能と理由が明示される。ここまでではSkillをロード・実行しない。

### P1: Agent Skills形式の限定的な読取り・検証

1. 静的fixtureの`SKILL.md`について、公式required fields、name/path一致、相対参照のルート外逸脱防止、サイズ/深さ/パス上限を検証。
2. メタデータだけを候補一覧へ露出し、**ホストに許可された現在のタスクとツール集合**から候補をモデルが選択できるようにする。汎用前段分類器や常時全Skill読込みは置かない。
3. 選択後にだけ内容を読む。外部由来Skillは未信頼データとして扱い、実行可能なscripts/依存パッケージは別途審査。ロード前後でdigest検証し、silent updateを拒否。
4. Claude/Codex/OpenCode等の互換は**読み込み形式の実機適合確認を通ったものだけ**有効にし、非対応CLIへ無理に共通化しない。

**合格:** 合法fixtureを選択でき、不正frontmatter、ルート逸脱、digest drift、Skill本文の「権限を追加せよ」指示は外部効果前に拒否。既存Agentの通常のツール選択と結果が退化しない。

### P2: 既存境界での3つの実務E2E

- **A / 公開情報調査 → 出典付き要約:** 公開固定URL/文章の取得 → 根拠を持つ要約と検証可能な出力。初期はネットワークなしfixtureで再現、次に公開固定課題のみ実機受入。個人情報・有料API・投稿を使わない。
- **B / 文書・表の変換 → 成果物検証:** 既存FILES/LibreChat/既存ローカル処理を用いて非機密fixtureを整形、構造・保存結果を独立読戻し。新しい汎用FILES write権限は開けない。
- **C / 開発課題の仕様整理 → Draft作業の引渡し:** Issue/PR/CIを読み、既存の開発受入契約へ非効力の候補を作成する。実装・worktree・Draft PR提出は既存開発実行所有者の条件が揃った場合のみ。Skillから開発セッションの新規制御をしない。

同一作業について「スキルなし既存Agent」と「スキル適用」を比較。成功率、出典/出力の検証率、工程時間、tokens、余計なツール呼出回数、復旧件数、権限逸脱ゼロを記録。**性能向上を仮定しない**。

**合格:** 3業務で合成試験と固定実データE2E、許可外効果ゼロ、入力/出力/Skill version/検証receiptを独立読戻しできる。既存UIから少なくとも1件の実用タスクが完走する。受入できなければ未完のまま残す。

### P3: Skillの学習・生成・改修候補

1. 結果が検証済みの繰返し作業に限り、次回再利用可能な手順を**候補として生成**。KLMのsource-provenanceを保持し、成功したというLLM自己申告は根拠にしない。
2. 静的仕様検証 → 固定fixtureテスト → 影響範囲だけの差分テスト → 独立検査 → **Draft PR**。同一内容のSkill生成をfingerprintで重複抑制。
3. 同一権限・同一公開範囲・既存の承認済み開発契約の範囲なら、通常コード修正と同様の自律候補化を許容する。一方、新しいツール、外部送信、課金、秘密、本人の価値判断、不可逆効果を要する場合は既存Guard/Human Gateで停止。
4. 版更新の前後比較とrollbackを記録。不採用のSkillも元の成功事例/否定証拠とともに履歴として残すが、巨大な実行ログ・Raw個人データをKLMへ複製しない。

**合格:** 1件を固定fixtureに基づき自動候補化し、独立テスト済みDraft PRと根拠・差分が揃う。生成結果を承認前に自動実行可能にしない。

### P4: 組み合わせ・複数入口（P2受入後）

既存Agent自身に最大2〜3スキルまで順序を選ばせる限定的な複合業務を測定。長期・副作用のある処理は既存のDurable Work/ExecutionPortに渡す。スマホ、MCP、日常チャットは**同じhost permission / Guard / output receipt**の別入口とし、状態/承認を複製しない。MCP Skills Extensionは将来の互換候補であり、機能上必要になるまで新サーバ・プロトコル実装をしない。

**合格:** 少なくとも1件の多段実務が途中失敗→安全な復旧→結果読戻しまで完走、同じ操作の重複効果ゼロ。UI・MCPの両方で承認台帳が一致する（MCP側の本番アダプター実装が別途受入済みの場合のみ）。

## 3. 課金・情報・モデル運用の不変条件

- **追加自動課金ゼロ。** モデル・外部サービスの導入選定は利用者の手動。無料アカウントの超過で有料へ自動移行しない仕組みを確認したものだけ利用し、無料枠は有効利用する。課金防止だけの不要な周期再承認／モデル数制限を新設しない。既存Free-route admissionの実行時境界に従う。
- 既存9B/local model slotの役割・開発優先・M1 compute leaseを保持。モデルの増設・強制停止や一律Thinking OFF、独自のモデルルーターを導入しない。
- Skill本文、外部検索結果、README、MCPレスポンス、出典不明の生成物は**instructionsではなくuntrusted content**として取り扱う。Prompt injection、権限混同、外部endpointへの情報持出しを固定テストで拒否。Skillに記された`allowed-tools`、`readOnlyHint`、CLIフラグをhost認可に使わない。
- 出力を「生成した」「保存した」「送った」などのモデル自己申告のみで完了としない。効果が不確実ならUNCERTAIN→独立読戻し→照合。再送・再決済・再投稿を禁止。
- 既存LV1〜LV5、HumanModel-first exception、通知の重複防止を維持。Skill起動の都度、通常の情報通知や人間確認を増やさない。
- 開発中の検証は影響範囲の合成テストを中心にし、本番切替前だけ現行の必要なCI・実機E2Eを通す。

## 4. 検証計画と失敗停止条件

| Gate | 観測するもの | 不合格時 |
| --- | --- | --- |
| G0 構造・所有者 | 正本と実コード対応、重複ゼロ、既存hot path非侵食 | 計画のみ保持、設計見直し |
| G1 規格 | 標準required fields、オンデマンド読み込み、参照パス、digest、license確認 | 当該Skill無効、既存Agent運転継続 |
| G2 権限 | Skill/toolメタから権限が増えない、Guardのexact scope一致 | 効果前にDENY、出力を証拠化 |
| G3 E2E | A/B/C固定fixtureと最小実務、出力独立読戻し | 未受入。モデル成功申告では完了にしない |
| G4 品質 | 既存Agent単独とのA/B、成功率・遅延・追加呼出・誤操作 | 効果がなければ機能廃止/限定 |
| G5 生成 | 新Skill候補1件の固定テスト→Draft PR、版更新rollback | 人間の追加承認より先に有効化しない |
| G6 実運用 | 同じGuardとreceiptのまま1件の日常入口E2E | 新入口を本番化しない |

未測定の目標値は**仮説**であり、KEITOの利用件数や速度をFoundationの実績に転記しない。特にP0〜P2では新しい常駐daemon、定期全Skill監査、大量Skill収集/一括import、専用判断LLM、別DBを作らない。

## 5. 実装担当者への最初の作業指示

1. まず本ファイルと`END_GOAL.md`、`SYSTEM_ROLE_BOUNDARIES.md`、`BOUNDARIES.md`、`NON_SELFDEV_BACKLOG_20261102.md`、現在のAgent/MCP/実行コードを**現在のHEAD**で読み、P0差分表を追記する。
2. 既存のスキルロード機能があればそれを拡張する。なければ**静的fixtureの読取+標準バリデータ**のみを最初のDraft PRに載せる。実機やprivate dataは触らない。
3. 各PRに「どの所有者の機能を再利用したか」「新規追加を断念した重複と理由」「既存E2Eとの実測差分」「未受入Gate」を明記する。
4. M1の固定ブリッジで可能な独立状態読戻しを優先、GitHubを次点とし、Desktop Commanderは他の経路で不可能な場合のみ。Kandev操作や開発ライフサイクルの重複新設をしない。
5. **本計画の登録は実装承認でも本番切替承認でもない。** 有料経路、mainマージ、Native信号、外部公開、秘密の持出し、第三者アカウント操作は行わない。

## 6. 調査で見送った構成

| KEITO等で見られる発想 | 本計画の結論 | 理由 |
| --- | --- | --- |
| Claude Codeを唯一の司令塔にする | 採用しない | Foundationのモデル交換可能性と既存一つのAgent loopを壊す |
| 常時全工程に判断AIを挟む | 採用しない | 証明されていない効果に対してコスト/遅延/権限混同の危険。Guardと独立検証で必要分だけ判断 |
| 150種類以上を一括導入 | 採用しない | 出自/ライセンス/実装依存/用途重複/品質の証明なし |
| Obsidianを第2記憶の正本にする | 採用しない | KLM・Drive・HumanModelの正本所有を侵す。必要なら将来読取アダプター |
| 独立したSkillジョブキューと定期監視 | 採用しない | 既存Runtime/開発OS/通知と重複 |
| Skills + MCPの共通規格を利用 | 採用候補 | 手順と操作を分離しながら可搬性を得られる |
| 業務成果物と検証済みノウハウを継続蓄積 | 採用候補 | 今のFoundationの日常業務E2Eの実用不足を埋められる |

**次の具体タスクはP0→P1のみ。** P2以降はGate前倒しで一括実装せず、測定した利得と実作業の必要性を見て進める。
