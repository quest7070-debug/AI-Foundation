# AI-Foundation｜自律開発承認機能の実装計画（2026-11-08）

**正本**: `quest7070-dev/AI-Foundation` の現在の `main`、既存 `docs/HUMAN_ESCALATION_POLICY_2026-10-06.md`、Guard/Operator/Durable Work。KLMや別AIを新しい承認の正本にしない。

## 基本方針

Foundation本体の能力と実態を優先する。既存Operatorの画面仕様を開発の前提にせず、まずGuard・既存自動開発ワーカー・実際の判断履歴から**読み取り専用の状態投影**を作り、設定画面・通知・Web Push・将来のMCPが同じ状態を使用する。

- 普通のプログラム作成／修正、固定テスト、失敗時の限定的な修正、隔離Draft PRまでは、**既存の事前許可済み開発契約に合致する限り完全自動**。課題ごとの人間承認は求めない。
- 意図・価値判断・既存委任範囲が不明な場合だけ、現行Canon、実行証拠、Guardを確認したうえで**HumanModelの承認済み・現行Viewを一次参照**する。過去の明示判断を正しい対象・版・権限で再検証した結果だけを用いる。HumanModelの推測・好み・欠落データを承認に変換しない。
- なお判断できない／権限拡張となる場合だけ`WAITING_HUMAN`。本番配備、秘密情報、課金、不可逆操作は既存の明示Human Gateを維持する。
- LV1〜LV5を再利用。HumanModel一次審査の**開始・結果**は既存LV2で通知、本人操作が必要ならLV4。通常の定期巡回やテストのたびに通知しない。
- 既存のM1 Bridgeは固定操作と証拠取得。汎用RDP/shellにせず、外部MCPは同じGuard権限・承認台帳を呼び出す薄いアダプターとする。

## 現状との対応（ソース確認）

| 現在の実装 | 使い方／不足 |
| --- | --- |
| `GuardCore.preflight` + `SQLiteGuardStore.approval_requests` | 権限・承認正本として利用。UIは以前、run IDだけで無条件承認できた。変更版への誤承認を防ぐ |
| `operator.snapshot` → `human_operations.notices` → `human_renderer` | 既存LV1〜LV5とAUTHORIZE/DENYを再利用。現行Guardのpendingだけを表示 |
| `OperatorApplication.human_payload` (`/api/human`) | Web Pushや将来MCPも共通投影から読み取る |
| `scripts/operator_server.py` Web Push | 既存投影の状態変化で配信。一次審査イベント生成と通知重複制御は未接続 |
| `HumanModelContext` と独立したHumanModel所有View | 現行承認済みView・スコープ・守秘条件の確認が必須。データ欠落時は自動人格判断しない |
| ローカル9B 5分周期／診断候補 | 普通のコード開発はそのまま自動。候補生成と安全な事前委任検査を連結する |
| GitHub→M1 Bridge／private Remote Gateway | 管理操作は専用固定ツールと認証を維持。拡張MCPは将来の別ポート |

## 実装優先順

### P0：現在のGuardにUIを追従させる【本PRの実装】

1. 現行`approval_requests`に**1要求固有のnonce**を追加（既存DBの要求は一回限り補完）。別DBや権限エンジンは作らない。
2. Guard要求の対象・操作が変更された場合だけnonceを更新。同じ要求を定期的に再観測しても失効しない。
3. Operatorの読取投影に`approval_ref`を付加し、HTMLの承認フォーム・`/api/human`から使用する。プライベートなtarget/source文字列は通知へコピーしない。
4. 本人がAUTHORIZE／DENYを実行したらDBの`BEGIN IMMEDIATE`下で**現在のpendingとnonceの完全一致を再検証**して1回だけ承認または取消を確定する。古いフォーム・置換済み・重複実行はどちらも拒否する。通常の実行取消は、承認待ちの拒否とは分離する。
5. 既存Guard内の直接`approve`権限を一般的な外部MCPへ公開しない。将来の他AIにも同じbounded `approve_pending`だけを使わせる。
6. 最小限の合成テスト: 実SQLiteで同一要求の安定、差し替え拒否、旧フォーム拒否、取消拒否、二重承認拒否、HTTPからの承認と読戻し、旧DB移行。

**効果**: 実際に承認待ちとなっているGuardの処理だけが画面から承認でき、設定画面を本体の実行契約に追随させる第一段階となる。これはHumanModel判断や外部MCPまで完成したことを意味しない。

### P1：自律開発とHumanModel一次審査を接続【後続】

1. 既存の自動開発候補・失敗分類器を採用し、機械的な小規模変更を既存の許可済みrecipeで自動実行。
2. 人間の判断に関する例外だけを現行HumanModel Viewの`decision`根拠・改訂・supersession・スコープで確認。入出力は既存のローカル専用プライバシー制限に従う。
3. 開始／結果のイベントを既存のHumanNotice／Web Pushへ投影。既存のイベント識別子・重複抑制を利用し、推論本文は通知しない。
4. 権限未充足や根拠不足はLV4へ停止。明示委任が適用可能でも、最後の実行可否は現行Guardが決定する。

### P2：設定画面を現行本体に追従【後続】

- 固定の擬似スイッチではなく、実稼働ワーカー・許可済みrecipe・Guard待機件数・HumanModel接続可能性を**現行ソースから**表示。
- 更新操作は現在の正本が受理するものだけ提供。受付不能な設定は無効表示とする。
- 開発課題の進捗はTASKS、一次審査開始/結果はLV2、本人対応はLV4、作用不明はLV5で統一。

### P3：外部AI向けMCP【後続】

- `foundation_status`, `approval_requests`, `review_candidate`, `submit_decision`を既存Guard/Operatorサービスのアダプターとして追加。
- 外部AIの推薦・要約は承認にしない。ホスト認証した本人もしくは対象別に明示委任された主体だけ`approve_pending`を呼べるようにする。
- 既存リモート画面・M1 Bridgeの認証方式を監査してからMCP接続。新規の任意shell、全ファイル書き込み権限を許可しない。

### P4：実M1受入

- 1件の普通のコード修正が**人間・HumanModelに一切聞かず**安全なDraft PRまで到達。
- 例外に対し一次審査開始/結果が各1回通知され、古い判断・別スコープの過去判断は無効。
- 本人判断が必要な項目はLV4として通知・承認・後続再開できる。
- UI／将来MCPの承認結果が同じGuard台帳へ反映され、同じ要求を二重承認しない。
- 既存リリースと独立した実行証拠を保存。mainマージ≠本番Operator反映。

## 運用・検証

開発中は変更対象の合成テストだけ実行し、毎回の全件テストを避ける。main統合と本番適用時には既存の独立したGuard・運用側の必要ゲートを保持する。Desktop Commander/Kandevへの依存を増やさず、M1 Bridge→GitHubを優先する。課金サービス・秘密情報・HumanModel原本の自動変更・既存Native/Guard権限の拡張は行わない。

**状態**: P0は本PRのコード・最小テストで検証。P1〜P4は未受入であり、実M1の本番承認の動作を確認するまでは完成扱いにしない。
