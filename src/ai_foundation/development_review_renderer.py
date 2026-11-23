"""Escaped owner-local CODE review drill-down in the existing Operator."""
from html import escape
import re


def render_review(csrf_token, preview=None, delegation_status=None,
                  pending_ids=(), pending_states=None):
    e = escape
    token = e(csrf_token, quote=True)
    heading = '<h1>CODE 開発依頼の審査</h1><p><a href="/">概要へ戻る</a></p>'
    if preview is None:
        body = (heading + '<form method="post" action="/development/review/preview">'
                '<input type="hidden" name="csrf" value="' + token + '">'
                '<label>保存済み依頼ID <input name="ticket_id" required maxlength="48" '
                'pattern="[a-z0-9][a-z0-9-]{0,47}"></label>'
                '<button type="submit">ソースと固定テストを確認</button></form>')
        if type(pending_ids) in (list, tuple) and pending_ids:
            # Existing owner-only page. A button only previews source/test;
            # it does not consent, approve Guard or start CODE execution.
            rows = tuple(ticket for ticket in pending_ids[:64]
                         if type(ticket) is str and
                         re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", ticket))
            if rows:
                body += ('<h2>未審査の保存済み依頼</h2><p>内容の確認のみ。'
                         'この画面から実行や承認は行いません。</p>')
                issue_labels = {
                    "REVIEW_SCOPE_SELECTION_REQUIRED": "変更対象のファイル指定が不足",
                    "SOURCE_NOT_PINNED_TO_HEAD": "変更対象ソースを正本で確認できません",
                    "TEST_NOT_PINNED_TO_HEAD": "独立した固定テストを正本で確認できません",
                    "LIVE_OPERATOR_SOURCE_UNVERIFIED":
                        "稼働中Operatorの正規ソースを確認できません（審査不可）",
                    "PINNED_SOURCE_OR_TEST_UNVERIFIED":
                        "正規ソースまたは独立固定テストの一致を確認できません（審査不可）",
                    "OWNER_CHECKOUT_NOT_CLEAN": "ローカル正本に未確定の変更があります",
                    "OWNER_CHECKOUT_CHANGED_DURING_REVIEW": "確認中に正本が変更されました",
                    "OWNER_LOCAL_REPOSITORY_UNVERIFIED": "ローカル正本を確認できません",
                    "PREVIEW_UNVERIFIED": "プレビューの前提条件を確認できません",
                }
                states = pending_states if type(pending_states) is dict else {}
                for ticket in rows:
                    safe = e(ticket, quote=True)
                    state = states.get(ticket, "PREVIEW_READY")
                    if state != "PREVIEW_READY":
                        label = issue_labels.get(state, "審査の前提条件を確認してください")
                        body += ('<p><strong>' + safe + '</strong>: '
                                 + e(label) + '</p>')
                        continue
                    body += ('<form method="post" action="/development/review/preview">'
                             '<input type="hidden" name="csrf" value="' + token + '">'
                             '<input type="hidden" name="ticket_id" value="' + safe + '">'
                             '<button type="submit">' + safe + ' の内容を確認</button></form>')
        state = delegation_status if type(delegation_status) is dict else {}
        active = state.get("status") == "ENABLED"
        body += ('<h2>通常CODEの委譲（1回設定・いつでも撤回）</h2>'
                 '<p>既存Guard・固定テスト・M1独立受入は省略しません。'
                 '権限・秘密・本番・ストレージなど保護対象は個別レビューに残します。</p>'
                 '<p>委譲状態: <b>' + e("有効" if active else "未有効 / 停止中") + '</b></p>'
                 '<form method="post" action="/development/delegation/enable">'
                 '<input type="hidden" name="csrf" value="' + token + '">'
                 '<label>実行先 <select name="model" required>'
                 '<option value="">選択してください</option>'
                 '<option value="m1">M1 9Bのみ（外部送信なし）</option>'
                 '<option value="auto">公開可能コードのみStrata優先・M1へフォールバック</option>'
                 '</select></label>'
                 '<label>検証済みDraftの配布 <select name="allow_draft_delivery" required>'
                 '<option value="">選択してください</option>'
                 '<option value="no">許可しない</option>'
                 '<option value="yes">許可する（mainは変更しない）</option></select></label>'
                 '<p><label><input type="checkbox" name="scope_confirmed" value="yes" required>'
                 '指定範囲内の今後の公開可能なCODE修正と固定テストを個別確認なしで実行させます。'
                 'Strata選択時のみ公開コードを外部PCに送ることを認めます。</label></p>'
                 '<button type="submit">委譲を有効化（実行は開始しません）</button></form>'
                 '<form method="post" action="/development/delegation/revoke">'
                 '<input type="hidden" name="csrf" value="' + token + '">'
                 '<label><input type="checkbox" name="revoke_confirmed" value="yes" required>'
                 '新しい自律開発とDraft配布の委譲を停止します</label>'
                 '<button type="submit">委譲を停止</button></form>')
    else:
        body = heading + '<p>実際の変更対象と独立した固定テストを確認してください。'
        body += 'ここではテストやモデルを実行しません。</p>'
        for label, field in (('依頼ID', 'ticket_id'), ('基点コミット', 'base_sha'),
                             ('変更対象', 'target'), ('固定テスト', 'test')):
            body += '<p>' + label + ': <code>' + e(preview[field]) + '</code></p>'
        for label, field in (('保存された依頼', 'instruction'),
                             ('変更対象ソース', 'target_text'), ('固定テスト', 'test_text')):
            body += '<h2>' + label + '</h2><pre>' + e(preview[field]) + '</pre>'
        body += ('<form method="post" action="/development/review/confirm">'
                 '<input type="hidden" name="csrf" value="' + token + '">'
                 '<input type="hidden" name="ticket_id" value="' + e(preview['ticket_id'], quote=True) + '">'
                 '<input type="hidden" name="preview_token" value="' + e(preview['preview_token'], quote=True) + '">'
                 '<label>実行先 <select name="model" required>'
                 '<option value="">選択してください</option>'
                 '<option value="strata">Strataのみ</option>'
                 '<option value="auto">Strata優先・利用不可時は共有9B</option>'
                 '<option value="m1">M1共有9Bのみ</option></select></label>'
                 '<p><label><input type="checkbox" name="source_reviewed" value="yes" required>'
                 '表示された依頼とソースの範囲を確認しました</label></p>'
                 '<p><label><input type="checkbox" name="test_reviewed" value="yes" required>'
                 '固定テストが目的を独立に検証することを確認しました</label></p>'
                 '<p><label><input type="checkbox" name="public_nonsecret" value="yes" required>'
                 '依頼とソースは公開可能で、秘密情報を含みません</label></p>'
                 '<button type="submit">審査を保存（コード実行なし）</button></form>'
                 '<h2>未受入の依頼を取り下げる</h2>'
                 '<p>既に修正済み、または不要になった依頼を実行せず終了します。審査記録は保持します。</p>'
                 '<form method="post" action="/development/review/cancel">'
                 '<input type="hidden" name="csrf" value="' + token + '">'
                 '<input type="hidden" name="ticket_id" value="' + e(preview['ticket_id'], quote=True) + '">'
                 '<input type="hidden" name="preview_token" value="' + e(preview['preview_token'], quote=True) + '">'
                 '<label><input type="checkbox" name="withdrawal_confirmed" value="yes" required>'
                 'この未受入の依頼を取り下げ、実行しないことを確認しました</label>'
                 '<button type="submit">依頼を取り下げる</button></form>')
    return ('<!doctype html><html lang="ja"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>CODE 審査 | AI Foundation</title>'
            '<style>body{max-width:1100px;margin:2rem auto;padding:0 1rem;font:16px system-ui}'
            'pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:1rem;background:#f2f4f7}'
            'button,select,input{font:inherit}button{padding:.6rem;margin:1rem 0}</style>'
            '<body>' + body + '</body></html>')

