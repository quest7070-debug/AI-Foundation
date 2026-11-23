# AI・機会探索: 回収済み共有チャットの全メッセージ監査（2026-10-01〜08）

調査日: 2026-11-01。**一次資料**: [共有スナップショット](https://chatgpt.com/share/6ac819d7-24bc-83e8-9eb7-ede28ed9ea43)（タイトル「AI・機会探索」）。2026-10-08の別チャットで報告された約1.9MBの共有データと同じ公開URLであることを確認した。共有ページの**抽出済み本文は27,096文字、10メッセージ（AI 9、本人1）**。公開共有ページの本文化された長さは元のHTML転送サイズ1.9MBとは異なる。**これは10月8日時点のスナップショットであって、その後までを含む元チャット全件ではない**。

## 2026-11-01 増分再検証：日時精度の訂正

共有ページ本文（27,096文字）を再取得し、見出しを数え直した結果、表示順の **AI 9件＋本人 1件＝10メッセージ** は再確認できた。ページ冒頭の日時表示は `Thu, Oct 1 at 9:00 PM` で、**タイムゾーンは本文から確定できない**。最終M10には「2026年10月8日の探索」と明記されている。一方、**M02〜M09それぞれの発話日時・日本時間の日付は共有ページ本文にない**。したがって、このファイル名の `20261001_08` は「最初と最後の表示上の範囲」を指す便宜的なラベルであり、M04 Strata / M05本人質問 / M06訂正を「10月1日」「10月8日」と日付確定する根拠にはならない。出来事の順序 `M04 → M05 → M06` は原文から確定できる。

## 0. 証拠の厳密な扱い

- 以下の `M01`〜`M10` は共有ページの**表示順の通番**。ChatGPT内部の `message_id` を確認したわけではないため、これを内部IDと称しない。
- `M01-M04, M06-M10` は過去AIの探索・提案・外部事実の**主張**であり、本人の採用/同意/好みではない。現時点の公式仕様/無料条件/性能の真偽も未検証。
- `M05` の「3060TI8gじゃだめ？」のみ共有ページ内の**本人発言**。M06はAI自身の前言修正であって、ユーザー承認ではない。
- 実装・購入・導入を、この共有履歴だけで実施済みと判断してはならない。元チャット以外の7月/9月/10月の議論は別出典として扱う。

## 1. メッセージ全件索引

| メッセージ | 発話主体 | 主題 | HumanModelで記録できるもの |
|---|---|---|---|
| M01 | AI | CLM-8B, PixelLeak, Xing4.0とローカル購入見送り | AI候補・注意事項。本人判断は**ない** |
| M02 | AI | Gemma 4+LiteRT-LM、Paper2Agent、Poolside Laguna、Ascend周辺 | AI候補の優先順位、費用・適合条件 |
| M03 | AI | Strands Decider 2B、Tuskira AI Agent Gateway、Muse Gadget SDK | 以前の候補の更新・構造吸収案 |
| M04 | AI | Strata 125B MoE、GPU/RAM/SSD分層、3060 Ti 8GBを要件で除外 | AIの初期判断・性能情報 |
| M05 | **本人** | **「3060TI8gじゃだめ？」** | M04の判断に対する明示的な再検討要求 |
| M06 | AI | 「12GB+ GPU要件」を足切りした前言を修正 | 訂正の履歴と、先行する判断M04へのリンク |
| M07 | AI | Magnitude、AMD Ross、LDraw Nova | 実測比較候補・見送りの理由 |
| M08 | AI | GitHub ReviewBench、Beam、Mistral Large 4、Gemini無料枠報道 | 評価基準と監視・保留 |
| M09 | AI | Strands Box、CloudflareのSOC構成、Tulip工場AI | 安全境界移譲案と参考事例 |
| M10 | AI | FreeInference、HybridInference、Free Inference Directory | 公開データ限定試験と無料情報検証 |

## 2. 主候補17件: その場での判断と実際に使える部分

以下は**当時のAI判定**であり、本人が了承したことを示さない。技術的な適合可否は現行正本との照合・再検証が必要。

| ID | 初出 | 候補 | 当時の判定・条件 | HumanModelでの扱い / 現実の用途 |
|---|---|---|---|---|
| O01 | M01 | CLM-8B | WATCH、NVIDIA/Linux中心でM1には弱い | 外部機会Raw。閉じた行動集合の非生成判定という**設計原理**だけ比較 |
| O02 | M01 | PixelLeak | Guardの禁止副作用設計を改善、OpenShell直接採用不要 | 失敗事例Raw。public repo新設・外部upload・秘密送信等のリスク条件 |
| O03 | M02 | Gemma 4 12B + LiteRT-LM | M1 16GBで既存負荷込みの一回限りPROBE、既存backend維持 | 仮説「別runtimeなら14B失敗を一般化できない」の検証計画 |
| O04 | M02 | Paper2Agent | 思想のみ、費用面で直接導入不要 | `source docs→verified capability` の証拠付きtool化 |
| O05 | M02 | Poolside Laguna API | 期間限定無料、CARD/QUOTA不明、CODE公開データのPROBE | 条件確認未完・費用リスク、永続providerと誤登録しない |
| O06 | M03 | Strands Decider 2B | M1向け小規模PROBE。Cedarのauthority置換禁止 | O01を**更新**する別候補。閉じた判定のみをモデルへ分離 |
| O07 | M03 | AI Agent Gateway | Foundation REDUCE候補、alpha本番導入不可 | proxy/log/credential等の責務を現行実装と逆対応付け |
| O08 | M03 | Muse Gadget SDK | 原理のみ、導入・新ハード購入不要 | 中央AIと物理capability endpointの分離 |
| O09 | M04 | Strata | WATCH、当初3060 Ti 8GBを足切り。M06でAIが修正 | **同一候補の条件改訂**を保持。購入決定と混同しない |
| O10 | M07 | Magnitude | 強PROBE。同一モデルで現行llama.cppとA/B、置換は後 | benchmark/probe/outcomeの関係設計に利用 |
| O11 | M08 | GitHub ReviewBench | reviewer選定の外部benchmark。独自Agentを増やさない | 精度・見逃し・誤警告・費用0の評価軸 |
| O12 | M08 | Reflection AI Beam | 重み/対応runtime未確認、WATCH | Local MoEハード判断保留の理由であり採用ではない |
| O13 | M08 | Mistral Large 4 | 重み公開/対応runtime待ち、WATCH | O12と同様。日時の古い公開予定を現在の事実にしない |
| O14 | M09 | Strands Box | M1 OSS強PROBE/REDUCE候補、previewで本番導入見送り | sandbox/egress/credential境界をFoundationのauthorityと分離 |
| O15 | M10 | FreeInference | 無料APIでも研究記録・外部転送あり、公開テスト限定 | **個人Evidence/機密データの入力先として不適格** |
| O16 | M10 | HybridInferenceのprefix cache修正 | Gateway本体不要、実コードのprefix保持を監査 | コスト・効率監査の原理。HumanModelそのものの機能ではない |
| O17 | M10 | Free Inference Directory | 機械可読探索入力としてWATCH。個別カード要否の矛盾あり | 外部候補Raw。自動provider登録や課金認可に使わない |

## 3. 脇に出た候補・除外事例も落とさない

| 出現 | 対象 | 元チャットの扱い / 残すべき証拠 |
|---|---|---|
| M01 | Xing4.0-29B-A4B | 量子化済みでもM1/3060 Ti常用条件に合わないとの**当時の判断** |
| M01 | 192GB Unified Memory機 | $6,000超と報告、10万円予算から除外 |
| M01, M09 | NVIDIA OpenShell | 禁止能力/agent containmentの先行比較対象、同じ提案を再通知しない |
| M02 | Huawei/DeepSeekのAscend・DeepGEMM/DeepEP/TileLang | 大規模環境向けで個人10万円候補には不適 |
| M03 | P40/MI50/MI60構成 | 電力・冷却・母艦費用を含めると決定打ではないとの比較 |
| M07 | AMD Ross | MCP+検証済み知識+skills等は既存の管理原理と重複で通知見送り |
| M07 | LDraw Nova | plan→generator→CAD→render→vision検査→修正という原理だけ保留 |
| M08 | DGX Spark | 価格が$4,999と報告、予算から除外 |
| M08 | Gemini無料枠の報道 | ConsumerとAPIの区別が未確認なのでprovider変更しない |
| M09 | Cloudflare SOCのsmall decider→専門LLM→synthesis | O01/O06の**新規候補ではなく追加実証**。最終合成AIは証拠取得不可 |
| M09 | Tulip/Tiffany工場AI | 製造現場の人員割当・再教育の参考。独立部品としての導入提案は見送り |
| M10 | 無料API providerカタログのカード条件矛盾 | 「一覧に掲載＝利用を許可」という誤昇格を禁止 |

## 4. 時系列で関係をつなぐ（単なる項目一覧では見えない部分）

1. **O01 CLM-8B→O06 Strands Decider 2B**: 非生成の小判断という同じ原理について、M1実行可能性の評価がWATCHからPROBEへ移る。候補は別物だが課題は重なる。ユーザーの好み変化ではない。
2. **O02 PixelLeak→O14 Strands Box**: 「禁止副作用」という失敗事例から実装候補へ発展。Guard/Cedarのauthorityは残す。発見だけで本番採用しない。
3. **O09 Strata M04→本人 M05→AI訂正 M06**: 最重要の明示的対話。要件による断定的足切りを本人の問いが覆し、既存8GBで試す方向に変わった。これを `USER_QUERY`→`ASSISTANT_RETRACTION` とし、本人による導入承認へ飛躍させない。
4. **M01/M03/M04/M07/M08/M09/M10の「10万円70B」**: 複数回「今すぐ買い」の新候補なし。通知対象がないことも探索結果。外部報告だけから恒久的な購買嗜好を推定しない。
5. **O05/O15/O17無料API**: 「無料」の意味は期間・quota・カード・第三者のデータ保存/公開・利用目的により変わる。HumanModelの個人Rawを外部無料APIへ送る用途は別審査。
6. **O03/O09/O10**: 機種別runtime適合の結論は負荷・メモリ・swap・速度の条件付き。古いベンチマークの人物属性化や推奨の固定化をしない。

## 5. HumanModelに取り込んでよい証拠と取り込んではいけない証拠

**採用可能（出典を明記し用途限定）**

- `USER_QUERY`: M05の本人の問い。前のAI断定に対する再検討要求であり、技術導入への関心/意図を過大解釈しない。
- `ASSISTANT_PROPOSAL`: M01-M04, M07-M10の各候補と当時の根拠・条件・推奨。機会探索の**提案履歴**であり、本人の性格データではない。
- `ASSISTANT_RETRACTION`: M06からM04への明示的改訂リンク。`supersedes`で誤判断を抹消せず、訂正経緯を見られるようにする。
- `NOT_RECOMMENDED`: 購入見送りや、不採用とした外部候補の理由（費用、機密、未成熟、重複）。
- `SOURCE_UNVERIFIED`: 過去のAIが紹介した発売日・URL・規約・性能・金額。外部公式再照合まで検証済みfactとして扱わない。

**禁止**

- 9件のAI報告を「ユーザーはこれら17技術を好んで採用した」と要約すること。
- FREEの外部LLMへChat履歴・個人Evidenceを送ること。
- Snapshot内の予定公開日を2026-11-01現在の事実とみなすこと。
- セキュリティ系PRや課金・provider設定を、探索チャットで紹介されたからといって自動実装すること。

## 6. 取得できていない範囲と正しい次の探索先

- 元チャットURL `https://chatgpt.com/c/6abeca1b-06f0-83e8-ba35-4e9cc479bd46` の**非公開会話の全期間**は未取得。
- 共有URLはスナップショット。10月9〜31日と11月1日の後続メッセージを含むとは言えない。
- 10月30日のDOCX整理・10月31日のApache Ossie/AGENTS.md/Groq比較は**他の文脈の回想情報**として得られるが、この公開スナップショットのメッセージではない。A等級（公開原本）に混ぜない。
- この監査が網羅しているのは**回収した共有スナップショット10メッセージと、 therein の主17候補・周辺例12行**であり、チャット全期間ではない。
