# 「AI・機会探索」10月9〜31日の欠落期間：二次検索索引

> **2026-11-03 一次原文回収による重要更新:** 11/1付のChatGPT公式エクスポートから、対象会話の10/09〜10/31 JSTのテキスト29件（AI 27、本人2）を直接確認した。10/09〜30の22日間には実質的な朝の報告があり、10/31はエラー通知のみ。以下のUTCログ日付／二次索引表は**歴史的な未回収時点の索引として保存するが、JST日付・候補帰属の正本ではない**。特に10/28のBonsai 2/3060 Ti 27B報告が抜けており、10/29以降の行は日付がずれていた。原文に基づくJST別の訂正表とRaw読戻し証拠は [OPPORTUNITY_EXPORT_20261103_AUDIT.md](./OPPORTUNITY_EXPORT_20261103_AUDIT.md) を優先する。実HumanModelへの本人採用イベントは自動生成しない。


監査日: 2026-11-01。
元会話ID: `6abeca1b-06f0-83e8-ba35-4e9cc479bd46`。
この日別索引は、**過去会話検索で得た「過去AIの当時の日次出力」の要約・日付**に基づく（出典等級B）。**各メッセージの全文・内部IDを直接再取得したのではない**。同様の話題が別会話にもあるため、候補に対する本人の同意や実装完了とは扱わない。

対して、10月1〜8日の公開共有原文10件は `OPPORTUNITY_SHARED_CHAT_20261001_08_AUDIT.md`、11月1日06:00の最新結果は `OPPORTUNITY_AUTOMATION_20261101_AUDIT.md` に**直接取得した別の証拠**がある。

> **増分訂正（2026-11-01）:** 共有原本のM01/M03/M09には個別日時が付いていない。従来の「10/1 CLM」「10/3 Decider」「10/7 Strands Box」という断定は原本からは支持されないため、メッセージ通番へ置換した。10/9〜31の以下の行も全文未回収の二次索引であり、日付の確定には当日のrun原文が必要。

## 1. 回収できた候補（日付は原則ログのUTC日付）

以下の「当日」は**過去ログのUTC日付（通常約21:00 UTC）**。日本時間06:00の自動実行は翌暦日となることに注意。要約文のラベルは日付が一日前後する場合があり、個々の正確なJST日付の確定は未完。分類は過去AIの評価であり**ユーザーによる採用ではない**。

| UTCログ日付 | 日次候補・評価の回収内容 | 未確定点 |
|---|---|---|
| 10/09 | Mellum2.1=小規模PROBE、Webcmd=独立Worker候補/WATCH | 性能・URL原文、実機結果 |
| 10/10 | Anthropic外部操作事故=READ/外部副作用境界監査、OpenCode Zen無料群/Jev 1.13 Free=請求情報要件で不採用 | 事故の一次資料、本人承認 |
| 10/11 | Hermes AgentのGit副作用=既存Git実行経路限定監査、Hermes移行せず | 実装との重複 |
| 10/12 | Kumo=小規模表/関係データの予測・独立PROBE | HumanModel潜在モデルとの適合実測 |
| 10/13 | Clef-omni=動画/音声/画像の選択式判定PROBE | 非生成Deciderとの重複・端末実測 |
| 10/14 | MiniCPM-V 4.7 / LES=MoE高速化の強PROBE、1B Vision低優先PROBE | 実性能、ライセンス、現環境適合 |
| 10/15 | LiteLLM依存の脆弱性監査、Apple Minions=遊休Mac分散推論の思想比較、導入なし | 正本の現状・分散効率 |
| 10/16 | speech.cpp=日本語STT/TTSの独立Worker PROBE、Industrial Edge RCS=WATCH | ローカル音声実測、製造設備の実用途 |
| 10/17 | GitHub Actions Lockfiles=優先PROBE、DXC OASIS=比較候補 | M1セルフホストrunnerとの適合 |
| 10/18 | Nemotron 3.5 Bolt 74B=重要WATCH、PS5LM Plus=WATCH、NVIDIA PAIR=保留 | 一次資料の仕様・必要VRAM |
| 10/19 | Nemotron Bolt/PS5LM Plus/PAIRの評価が別の日付ラベルにも出現 | 同一回の重複索引の可能性があり**独立の新規報告と数えない** |
| 10/20 | Timestral=PROBE、MiniMax M3.1 Flash=条件付き比較、CMP 170HX=見送り | モデル/ハード実測と無料条件 |
| 10/21 | OrcaRouter=導入可能候補、Tev1=原理移植/PROBE、Reflection Beam=期限付き利用機会 | provider重複、期限、現仕様 |
| 10/22 | LiteLLM 1.107.0配布物改ざん=MultiLLMへの影響確認、OpenCode Console事故=直接被害未確認・APIキー保存有無の確認 | 依存バージョン、被害の事実 |
| 10/23 | freehire=導入候補、ALTK-Evolve=原理比較 | 後に10/30整理では除外、理由の追跡が必要 |
| 10/24 | FreeInference=条件付き導入、NTT関連=原理比較 | 10/8共有のFreeInferenceとの差分、研究データ取扱い |
| 10/25 | M365外部アプリ権限監査=既存業務改善 | 会社情報を自動送信する権限はない |
| 10/26 | Decider for Mac=M1ローカル分類の優先度高、Flint無料API=公開情報限定比較、ネットワーク有無でAgent評価差 | Decider関連とO06との重複・実測 |
| 10/27 | Resonant=独立導入候補、Containarium/Scope=設計比較、70B級ハード購入は見送り | Resonantの用途とFoundation境界 |
| 10/28 | LFM3-Audio-2B＋llama.cpp=ローカル音声試験、Nemotron Super VL=公開情報限定無料API、Agent Reach 1.6.0=公開情報源限定 | 無料条件、個人Rawの外部送信は禁止 |
| 10/29 | GitHub Agentic Workflows=読み取り専用CI失敗調査候補、Copilot Fusion=思想、Replica=独立UI試作 | Actions費用、既存自動開発との競合 |
| 10/30 | GitHub Agentic Workflows/GLM-4.7-Flash=比較、Replica=UI試作、Fusion/Automations/WorkflowOps=思想、Paperclip=不採用 | 10/30 7ページ候補一覧との一致確認は未完 |
| 10/31 | Apache Ossie/AGENTS.md/Groq Qwen3.8 27B/FreeInference.dev/P100複数枚 | **11/1日本時間06:00の自動化直接結果を別ファイルに保存** |

### 2. 絞り込むべき「ユーザー判断」の不足

公開共有チャット10件で確認した本人発言は `3060TI8gじゃだめ？` だけ。この二次索引には、本人が毎日候補の採否を返信したことを示す確定原文がない。したがって、ここに記載した大量の「採用」「導入可能」は**AIの選定状態**であり、ユーザーのPreference・Decision・Outcomeとは別。

### 3. 重大な状態変化（必ず分離して保持）

1. `FreeInference`: 10/8=研究ログ可能性がある公開コード限定PROBE、10/24=条件付き導入、10/30=情報不足による除外、11/1=無料Directory参考データのみ採用。似た名称の**無料API本体とDirectoryを別ID**にする。
2. `Nemotron`: 10/18=Bolt WATCH、10/28=Super VL無料API、10/30=候補整理。**Bolt推論用ハードとSuper VLのクラウドAPIを混同しない**。
3. `Decision Models`: 共有原本M01 CLM原理→M03 Strands Decider（個別日付未確認）→10/13 Clef-omni→10/26 Decider for Mac。候補それぞれは別だが「少ない選択肢から高速判定」という機能重複は後段評価。
4. `Actions`: 10/17 Lockfiles（依存固定）、10/29 Agentic Workflows（CI調査）。似たGitHub Actionでも責務は別。
5. `Security`: 共有原本M01 PixelLeak、M09 Strands Box（個別日付未確認）、10/10 外部操作事故、10/11 Hermes Git副作用、10/15/22 LiteLLM、11/1 AGENTS.md。攻撃入口・依存・副作用・認可を一つのセキュリティイベントへ圧縮しない。
6. `speech/audio`: 10/16 speech.cpp、10/28 LFM3-Audio、10/30 speech.cpp整理。実際の音声原本、文字起こし、話者識別、同意・承認を混同しない。
7. `hardware`: 10万円/70B超の条件で否定的な日次結果を繰り返し報告。これを「永久にGPUを買わない」「固定的に特定メーカーを好む」とは解釈しない。

### 4. HumanModel導入の現実的な位置付け

- **P0**: 日次探索結果を `AssistantSuggestion` として候補と状態・時刻・sourceを保管。本人に採用されたというイベントは別の本人発言/実行証拠がある時だけ。
- **P0**: 同じ候補の `WATCH → PROBE → rejected`、導入条件の改訂、外部の無料条件の変更をsource付きで保持する。状態変化を人物像の変化に読み替えない。
- **P1**: Rawの発見を行う独立探索段階にはHumanModelを入力しない。発見後にのみ目標・制約・実施済み経験・未試行を比較する。Concept OSの「完全独立探索」と「目標起点探索」は別ルート。
- **P1**: 文書・ソフトウェア・APIを過去AIが「使える」と報告しても、本人の環境で使えた `VerifiedOutcome` ではない。
- **不採用**: 過去の毎朝の候補一覧を「本人がこれに興味を持つ性格」という固定特性へ自動変換。

### 5. まだ全件取得できていないもの

上表は日次出力の**要約索引**。全文（候補のサブ項目・比較対照・詳細URL・採否変遷の原文・ユーザー返信・後続成果物）は未取得。元スレッドそのものの全発言を読んだとは主張しない。全候補件数と独立実行回数もこの表から確定させない。
