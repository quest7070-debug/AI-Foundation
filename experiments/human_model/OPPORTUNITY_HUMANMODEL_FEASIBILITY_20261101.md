# HumanModelに使えるもの・使えないもの：実装照合（2026-11-01）

この判断は一次共有チャット10メッセージ、11/1の定期実行直接結果、10/9〜31の検索要約と、`main`の実ソースを比較したもの。出典レベルは混ぜない。

## A. 既存コードで可能なこと

| 現行コード | 実装されている責務 | 境界 |
|---|---|---|
| `human_model_ledger.py` | Evidenceのsource_uri/revision、observed_at、kind、scope、privacy、SHA256、supersedes、disputed、view stale管理 | **evidence kindは5種類のみ**。actor, event type, user acceptanceを専用フィールドで持たない |
| `foundation_readonly.py` | approved view/scope/privacyによる読み取りのみ、SSD mount検証 | 呼出元認証やGuard強制が完成しているわけではない。プライバシー分類修正はPR #77の未統合状態 |
| `hypothesis_engine.py` | support/contraの証拠ID、scope、矛盾、uncertainty | 発言者・証拠種類を区別せず、AI提案が本人の同意として混入することを単体では防がない |
| `temporal_comparison.py` | model/producer/revisionごとの差分・矛盾を保持 | **出来事の因果関係ではなく仮説スナップショットの比較**。本人の訂正イベントそのものは別に表現が必要 |
| `proposal_evaluation.py` | untrusted提案を証拠IDと照合 | proposalが「ユーザー承認」を意味することはない |

## B. いまの時点で実際に組み込めるもの

**P0: 出典と発話主体を分ける（必要、低コスト）**

- `source_conversation_id`, `source_snapshot_url`, `source_message_ordinal`, `actor=user|assistant|automation|external`, `source_quality=direct|summary_only`。
- `M05`は本人の質問として、`M06`は過去AIによる前言撤回として、`M01..M04,M07..M10`は提案履歴として扱う。
- 共有ページの10個の表示順をChatGPTの内部message IDと偽らない。
- 現行Ledgerは上記すべてを専用フィールドで区別できないため、**既存schemaへ無理に詰めず、Proposal/Interactionの別イベント契約を先に定義する**。

**P0: 意思決定ではない推薦を意思決定へ自動昇格しない（必要）**

- `ASSISTANT_RECOMMENDATION` と `USER_ACCEPTANCE` は別。
- 明示実行の証拠が無い場合は `OUTCOME_UNKNOWN`。過去AIが「導入候補」と書いても実行済みではない。
- **共有スナップショット内の順序 M04 Strata** `AI_ASSERTION` → **M05本人の疑義** `USER_QUESTION` → **M06直後のAI訂正** `AI_RETRACTION` とリンク。共有ページには各メッセージの個別日時がないため「10/1 Strata」「10/8本人質問」とは確定しない。本人がStrataを採用したというイベントは生成しない。

**P1: 同一機会の改訂・追跡（必要）**

- FreeInference(API本体) と Free Inference Directory(カタログ)は別ID。初出、評価変化、Source Conflicts、期限切れを保持。
- CLM-8B/Strands Decider/Clef-omni/Decider for Macは各機会IDを保ち、共通の`capability=bounded_action_selection`で*評価時にだけ*比較。意味リンクを正本化しない。
- 無料APIのquotaは第三者カタログと公式に相違がある場合 `unresolved` にする。支払い手段/秘密/個人Evidenceの送信を禁止。

**P1: 日次AI探索とConcept OS独立探索の分離（必要）**

- 日次AI探索の出力は外部候補とAI分析。
- Concept OSの完全独立探索にはHumanModelの個人情報を渡さない。目標起点探索は別ルート。
- 発見後の実行可能性評価だけ、承認済みEvidenceと本人の明示目標・費用・環境制約を参照する。
- Opportunity→Chat→Concept→Reviewは操作由来のIDリンクを残し、AIが勝手に進めない。

## C. HumanModelのコアへ導入しないもの

- CLM、Decider、Magnitude、Strata、紙→tool化、GitHub CI自動化、Agent Gateway、Strands Box等は**技術・実行基盤の候補**。これらの製品をHumanModelへ丸ごと統合する理由は原文にない。
- Ossieは意味辞書/交換形式の参考。人物像・経験・意思決定の最終authorityへは昇格させない。
- 公開無料API（FreeInference等）へ人間モデルの私的Rawを渡す設計は不採用。
- 10万円70Bハード探索や購入保留を、固定的な好み・人格のラベルとして保存しない。

## D. 現在の実装検証での障害

11/1にmain統合された `human-model-m1-ollama-smoke.yml` のM1実機ジョブ `41252801911` は **FAILURE**。原因は `HUMAN_MODEL_OLLAMA_MODEL` リポジトリ変数が空でスクリプトが `BLOCKED: explicitly configure HUMAN_MODEL_OLLAMA_MODEL` で停止したため。**LLM推論へ到達しておらず、Ollamaの実機性能が悪いとの結論ではない**。

`PR #77` のCIも失敗しているが、ログ上の失敗は `tests/test_provider_recovery.py::test_recovery_loop_survives_transient_credentials_db_failure` で **1 failed / 1419 passed / 10 skipped**。プライバシー修正が不正と証明されたわけではない。Focused testsを分離して検証する必要がある。

## E. 明確な完成条件

1. 出典・発話者・時刻・命題・本人承認・訂正を区別するイベント契約を実装し、M04/M05/M06とFreeInference変更履歴で回帰を通す。
2. HumanModelへ入れる対象は、原文と本人許可がある範囲のみ。探索結果本文の一括人格化は禁止。
3. M1の実ローカルLLM検証は、モデル選択を自動・無料・localhost限定で完走するまで未達。
4. Foundationのread-only privacy一致修正は、関連Focused tests成功と正式統合を確認するまで未達。
5. 10/9〜31の全本文未取得は、二次索引の出典品質として明示し続ける。
