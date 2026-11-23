"""Publish only the user's explicit, project-scoped instructions from this chat.

These are supplied user messages, not extracted personal traits or model output.
Their event times and conversation IDs are unknown; neither is manufactured.
"""
import hashlib
import json

SCOPE = 'ai-foundation-development'
VIEW = 'foundation-development-instructions'
PURPOSE = ('Explicit AI-Foundation development instructions supplied by the owner; '
           'project context only, not a general personality or execution authority.')
MESSAGES = (
    ('human-model-boundary', '2の詳細気になるな。軽い記憶系はLLMや、ファンデーション機能でよいが、私の判断やパーソナライズ的な方は人間モデルから参照させる。'),
    ('development-boundary', 'ここではAIfaundation開発の未開拓部分を進めてほしい。今の開発は自己開発機構を進めているので、それ以外の部分を網羅的に調べて重要度順番に進めて。デスクトップコマンダーの消費は極力避け、m1適応はgithub経由。'),
)


def source_rows():
    return [dict(source_uri='conversation-excerpt:ai-foundation-development/'+name,
                 source_revision=hashlib.sha256(text.encode()).hexdigest(),
                 content=text, kind='instruction', scope=SCOPE, privacy='private',
                 observed_at=None) for name, text in MESSAGES]


def publish(ledger):
    """Idempotent explicit-source publication; never imports Raw or AI reviews.

    Preflight every existing record before adding anything. A partial first
    attempt is retryable; the view stays stale until the complete readback.
    """
    rows = source_rows()
    expected = {(r['source_uri'], r['source_revision']): r for r in rows}
    existing = ledger.db.execute(
        'SELECT source_uri,source_revision,content,kind,scope,privacy,observed_at,'
        'supersedes,disputed FROM evidence WHERE scope=?', (SCOPE,)).fetchall()
    for uri, revision, content, kind, scope, privacy, observed, supersedes, disputed in existing:
        row = expected.get((uri, revision))
        if row is None or (content, kind, scope, privacy, observed, supersedes, disputed) != (
                row['content'], 'instruction', SCOPE, 'private', None, None, 0):
            raise ValueError('existing project sources need explicit reconciliation')
    view = ledger.db.execute(
        'SELECT purpose,audience,allowed_scopes,max_privacy,revision,stale '
        'FROM model_views WHERE id=?', (VIEW,)).fetchone()
    if view and (view[0], view[1], json.loads(view[2]), view[3]) != (
            PURPOSE, 'foundation', [SCOPE], 'private'):
        raise ValueError('existing project view differs')
    ids = [ledger.add(**row) for row in rows]
    if not view:
        ledger.define_view(view_id=VIEW, purpose=PURPOSE, audience='foundation',
                           allowed_scopes=[SCOPE], max_privacy='private')
    current = ledger.db.execute('SELECT revision,stale FROM model_views WHERE id=?', (VIEW,)).fetchone()
    selected = {r[0] for r in ledger.db.execute(
        'SELECT evidence_id FROM model_sources WHERE model_id=?', (VIEW,))}
    if current[1] or selected != set(ids):
        revision = ledger.rebuild_view(view_id=VIEW)
    else:
        revision = current[0]
    found = ledger.query(view_id=VIEW, scope=SCOPE, audience='foundation', max_privacy='private')
    if {r['id'] for r in found} != set(ids):
        raise ValueError('complete explicit-source publication required')
    return {'view_id': VIEW, 'scope': SCOPE, 'view_revision': revision,
            'source_count': len(ids), 'source_event_times_known': False,
            'source_conversation_ids_known': False, 'generated_personal_traits': 0}
