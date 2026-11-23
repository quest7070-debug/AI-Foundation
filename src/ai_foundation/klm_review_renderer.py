"""Existing Operator drill-down for explicit source-grounded KLM decisions."""
from html import escape
from urllib.parse import quote

from .human_styles import styles
from .knowledge_lifecycle import RELATIONS


def _hidden(name, value):
    return '<input type="hidden" name="' + escape(name, quote=True) + '" value="' + escape(str(value), quote=True) + '">'


def render_klm_review(csrf, *, listing=None, preview=None, result=None, theme="I"):
    e = lambda value: escape(str(value), quote=True)
    body = '<header class="hero"><small>KLM / RELATION REVIEW</small><h1>関係の審査</h1></header>'
    if result is not None:
        body += '<section><h2>記録結果</h2><p>' + e(result.get('status', 'UNVERIFIED')) + '</p>'
        body += '<p>判断は元の候補を残して保存しました。</p><a href="/klm/review">候補一覧へ戻る</a></section>'
    elif preview is not None:
        body += '<section><p>原本の抜粋を確認し、この二つの情報の関係を判断してください。意味の正しさを自動認定する画面ではありません。</p>'
        body += '<p>審査理由: ' + e(preview['reason']) + ' · 範囲: ' + e(preview['scope']) + '</p>'
        for label, key in (('比較元', 'before'), ('比較先', 'after')):
            atom = preview[key]
            body += '<h2>' + label + '</h2><p>' + e(atom['resource_id']) + ' / ' + e(atom['record_id']) + ' · 版 ' + e(atom['revision']) + '</p>'
            body += '<pre>' + e(atom['span_text']) + '</pre><details><summary>照合情報</summary>'
            for name in ('atom_id', 'source_sha256', 'span_sha256', 'meaning_sha256'):
                body += '<p>' + e(name) + ': <code>' + e(atom[name]) + '</code></p>'
            body += '</details>'
        body += '<form method="post" action="/klm/review/confirm">'
        for name, value in (('csrf', csrf), ('review_key', preview['review_key']), ('preview_token', preview['preview_token'])):
            body += _hidden(name, value)
        body += '<label>判断 <select name="decision" required><option value="">選択してください</option><option value="ACCEPT">関係を採用</option><option value="REJECT">候補を却下</option></select></label>'
        body += '<label>関係の種類（採用時） <select name="relation_kind"><option value="">却下時は指定なし</option>'
        labels = {'supports': '支持する', 'contradicts': '矛盾する', 'supersedes': '置き換える', 'refines': '詳細化する', 'depends_on': '依存する', 'same_as_candidate': '同一情報の候補', 'derived_from': '派生する', 'preserves_goal': '目的を維持する', 'changes_priority': '優先度を変更する'}
        for kind in sorted(RELATIONS):
            body += '<option value="' + e(kind) + '">' + e(labels.get(kind, kind)) + '</option>'
        body += '</select></label><p>方向は「比較元 → 比較先」です。採用しても原本を変更する権限にはなりません。</p>'
        body += '<label><input type="checkbox" name="reviewed" value="yes" required>原本・方向・判断内容を確認し、この判断を承認します</label>'
        body += '<p>確定済みの判断は上書きしません。判断できない場合は一覧へ戻って保留できます。</p>'
        body += '<button class="ui-button role-confirm" type="submit">この判断を承認して保存</button></form></section>'
    else:
        body += '<section><h2>未審査の候補</h2><p>選択しても原本の変更や判断の確定は行いません。</p>'
        rows = (listing or {}).get('reviews', ())
        if not rows:
            body += '<p>この一覧に未審査候補はありません。</p>'
        for row in rows:
            body += '<div class="row"><p>' + e(row['reason']) + ' · ' + e(row['scope']) + ' · ' + e(row['privacy']) + '</p>'
            body += '<form method="post" action="/klm/review/preview">' + _hidden('csrf', csrf) + _hidden('review_key', row['review_key'])
            body += '<button class="ui-button role-secondary" type="submit">原本を確認して審査</button></form></div>'
        if (listing or {}).get('more') and (listing or {}).get('next_cursor'):
            body += '<p><a href="/klm/review?after=' + quote(listing['next_cursor'], safe='') + '">次の候補へ</a></p>'
        body += '</section>'
    css = styles('responsive', theme if theme in {'C', 'I'} else 'I')
    css += 'pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:32rem;overflow:auto;padding:1rem;border:1px solid #29485b}code{overflow-wrap:anywhere}label{display:block;margin:1rem 0}label input[type=checkbox]{width:auto}button{cursor:pointer}details{margin:1rem 0}'
    return ('<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>KLM 関係審査 | AI Foundation</title><style>' + css + '</style><body><main><nav><b>AI FOUNDATION</b>'
            '<a href="/">OVERVIEW</a><a href="/klm/review">KLM 関係審査</a><a href="/development/review">CODE 審査</a></nav><div class="content">' + body + '</div></main></body></html>')
