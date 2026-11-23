"""Shareable project-document view, separate from private owner originals.

Only two pinned excerpts already present in the authorized GitHub project are
eligible. No private ledger record is reclassified or copied into this view.
"""
import hashlib
import json
from pathlib import Path

REVISION = '36719b7bb19db805fc2ad665b353a7c96c8a67a3'
SCOPE = 'ai-foundation-project'
VIEW = 'foundation-project-reference'
PURPOSE = 'Pinned GitHub project documentation; no private owner history or execution authority.'
DOCUMENTS = (
    ('docs/COGNEE_INTEGRATION_20261103.md',
     '6096bbdd382e794971aee1f0772dcf7d0a1c5c589c7e8386edc802628832bd62',
     'SQLite remains the authority', 'permitted originals.'),
    ('docs/LOCAL_MODEL_ROLE_POLICY.md',
     '8509336b43671c7b9db9eb98e873227b1f1ec51b68155d51b3324c22ec71501f',
     '9B restoration or installation is not a prerequisite', 'or select the output LLM.'),
)


def source_rows(repository_root):
    rows=[]
    for relative,pin,start,end in DOCUMENTS:
        path=Path(repository_root)/relative; data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=pin: raise ValueError('pinned project document changed')
        text=data.decode(); begin=text.index(start); finish=text.index(end,begin)+len(end)
        rows.append(dict(source_uri=f'https://github.com/quest7070-dev/AI-Foundation/blob/{REVISION}/{relative}',
            source_revision=REVISION,kind='observation',scope=SCOPE,privacy='shareable',
            observed_at=None,content=text[begin:finish]))
    return rows


def publish(ledger, repository_root):
    rows=source_rows(repository_root)
    permitted={(r['source_uri'],r['source_revision']):r for r in rows}
    for uri,revision,content,privacy,kind,observed,disputed,supersedes in ledger.db.execute(
            'SELECT source_uri,source_revision,content,privacy,kind,observed_at,disputed,supersedes '
            'FROM evidence WHERE scope=?',(SCOPE,)):
        row=permitted.get((uri,revision))
        if row is None or (content,privacy,kind,observed,disputed,supersedes)!=(
                row['content'],'shareable','observation',None,0,None):
            raise ValueError('project reference scope requires reconciliation')
    current=ledger.db.execute('SELECT purpose,audience,allowed_scopes,max_privacy FROM model_views WHERE id=?',
                              (VIEW,)).fetchone()
    if current and (current[0],current[1],json.loads(current[2]),current[3])!=(
            PURPOSE,'foundation',[SCOPE],'shareable'):
        raise ValueError('project reference view differs')
    ids=[ledger.add(**row) for row in rows]
    if not current:
        ledger.define_view(view_id=VIEW,purpose=PURPOSE,audience='foundation',
                           allowed_scopes=[SCOPE],max_privacy='shareable')
    old=ledger.db.execute('SELECT revision,stale FROM model_views WHERE id=?',(VIEW,)).fetchone()
    selected={r[0] for r in ledger.db.execute('SELECT evidence_id FROM model_sources WHERE model_id=?',(VIEW,))}
    if old[1] or selected!=set(ids):revision=ledger.rebuild_view(view_id=VIEW)
    else:revision=old[0]
    found=ledger.query(view_id=VIEW,scope=SCOPE,audience='foundation',max_privacy='shareable')
    if {r['id'] for r in found}!=set(ids):raise ValueError('project source projection incomplete')
    # Global invalidation is conservative. Refresh only the known original
    # development view if its exact originals and definition remain unchanged.
    import development_sources
    private_refreshed=False
    private_count=ledger.db.execute('SELECT COUNT(*) FROM evidence WHERE scope=?',
                                   (development_sources.SCOPE,)).fetchone()[0]
    if private_count==2 and ledger.db.execute('SELECT 1 FROM model_views WHERE id=?',
                                            (development_sources.VIEW,)).fetchone():
        try:
            development_sources.publish(ledger);private_refreshed=True
        except ValueError:pass
    return {'view_id':VIEW,'scope':SCOPE,'view_revision':revision,
            'source_ids':ids,'project_document_count':len(ids),
            'private_originals_reclassified':0,'original_view_refreshed':private_refreshed}

