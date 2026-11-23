"""Foundation-facing read-only access to approved current HumanModel views."""
from __future__ import annotations
import hashlib
import json
import sqlite3
from pathlib import Path
if __package__:
    from .human_model_ledger import PRIVACY
else:
    from human_model_ledger import PRIVACY


def read_view(root: str | Path, *, view_id: str, scope: str,
              max_privacy: str = 'private', volumes_dir='/Volumes', mount_check=None,
              collection_current=None) -> list[dict]:
    """Legacy source-facing list interface; retain its record shape."""
    snapshot = _snapshot(root, view_id=view_id, scope=scope, max_privacy=max_privacy,
                         volumes_dir=volumes_dir, mount_check=mount_check,
                         max_records=None, max_bytes=None, offset=0,
                         collection_current=collection_current)
    return [{k: v for k, v in row.items() if k != 'content_sha256'} for row in snapshot['records']]


def read_view_snapshot(root: str | Path, *, view_id: str, scope: str,
                       max_privacy='private', max_records=32, max_bytes=32768,
                       offset=0, volumes_dir='/Volumes', mount_check=None,
                       collection_current=None) -> dict:
    """Bounded, revision-bound snapshot for an authenticated Foundation caller."""
    for value, low, high in ((max_records, 1, 128), (max_bytes, 1024, 131072), (offset, 0, 4096)):
        if type(value) is not int or not low <= value <= high:
            raise ValueError('bounded HumanModel page required')
    return _snapshot(root, view_id=view_id, scope=scope, max_privacy=max_privacy,
                     volumes_dir=volumes_dir, mount_check=mount_check,
                     max_records=max_records, max_bytes=max_bytes, offset=offset,
                     collection_current=collection_current)


def _snapshot(root, *, view_id, scope, max_privacy, volumes_dir, mount_check,
              max_records, max_bytes, offset, collection_current):
    if __package__:
        from .storage_location import validated_ledger_path
    else:
        from storage_location import validated_ledger_path
    if not view_id or not scope or scope == '*':
        raise ValueError('explicit view and non-wildcard scope required')
    if max_privacy not in PRIVACY:
        raise ValueError('unsupported privacy level')
    path = validated_ledger_path(root, volumes_dir=volumes_dir, mount_check=mount_check)
    if not path.is_file():
        raise FileNotFoundError('external ledger unavailable')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        view = db.execute('SELECT audience,allowed_scopes,max_privacy,stale,revision,purpose '
                          'FROM model_views WHERE id=?', (view_id,)).fetchone()
        if view is None or view[0] != 'foundation' or view[3] or type(view[4]) is not int or view[4] < 1:
            raise PermissionError('approved current Foundation view required')
        allowed_scopes=json.loads(view[1])
        if (not isinstance(allowed_scopes,list) or any(not isinstance(x,str) or x=='*' for x in allowed_scopes)
                or scope not in allowed_scopes):
            raise PermissionError('scope not approved')
        if view[2] not in PRIVACY or PRIVACY[max_privacy] > PRIVACY[view[2]]:
            raise PermissionError('privacy exceeds view ceiling')
        levels = tuple(k for k, value in PRIVACY.items() if value <= PRIVACY[max_privacy])
        marks = ','.join('?' for _ in levels)
        order = 'e.observed_at,e.id' if max_records is None else 'e.observed_at DESC,e.id'
        sql = ('SELECT e.id,e.kind,e.scope,e.content,e.source_uri,e.source_revision,'
               'e.observed_at,e.privacy,e.disputed,e.content_sha256 '
               'FROM model_sources ms JOIN evidence e ON e.id=ms.evidence_id '
               f'WHERE ms.model_id=? AND e.scope=? AND e.privacy IN ({marks}) ORDER BY {order}')
        params = (view_id, scope, *levels)
        if max_records is not None:
            sql += ' LIMIT ? OFFSET ?'; params += (max_records + 1, offset)
        # A host-admitted source is never served on the strength of an old
        # View membership alone. A trusted current-Guard consent checker is
        # mandatory for all *new* admitted evidence. Legacy source records
        # without admission proofs retain their original read contract.
        live_proofs = []
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                      "AND name='human_source_admissions'").fetchone():
            checks = db.execute(
                "SELECT a.state,a.consent_id_sha256 FROM model_sources ms "
                "JOIN human_source_admissions a ON a.evidence_id=ms.evidence_id "
                "JOIN evidence e ON e.id=ms.evidence_id "
                "WHERE ms.model_id=? AND e.scope=?",
                (view_id, scope),
            ).fetchall()
            for state, consent_sha in checks:
                if state != 'ACTIVE' or not callable(collection_current):
                    raise PermissionError('current owner collection grant required')
                try:
                    permitted = collection_current(consent_sha)
                except Exception:
                    permitted = False
                if permitted is not True:
                    raise PermissionError('collection grant revoked or unavailable')
                live_proofs.append(consent_sha)
        rows = db.execute(sql, params).fetchall()
        fields = ('id', 'kind', 'scope', 'content', 'source_uri', 'source_revision',
                  'observed_at', 'privacy', 'disputed', 'content_sha256')
        records = []; used = 0; consumed = 0; omitted = []
        window = rows if max_records is None else rows[:max_records]
        for row in window:
            item = dict(zip(fields, row))
            if (not isinstance(item['content'], str) or
                    hashlib.sha256(item['content'].encode()).hexdigest() != item['content_sha256']):
                raise ValueError('HumanModel evidence digest mismatch')
            size = len(json.dumps(item, ensure_ascii=False).encode('utf-8'))
            if max_bytes is not None and used + size > max_bytes:
                if not records:
                    omitted.append(item['id']); consumed += 1
                break
            records.append(item); used += size; consumed += 1
        truncated = consumed < len(rows)
        result = {'view_id': view_id, 'scope': scope, 'view_revision': view[4],
                  'records': records, 'truncated': truncated, 'omitted_record_ids': omitted,
                  'next_offset': offset + consumed if truncated else None}
        # Receipt identifies exactly the source snapshot returned, not a learned profile.
        result['snapshot_sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True,
                                               ensure_ascii=False).encode()).hexdigest()
        # Recheck authorization after reading private content, immediately
        # before crossing the host/read-tool boundary.
        for consent_sha in set(live_proofs):
            try:
                approved = collection_current(consent_sha)
            except Exception:
                approved = False
            if approved is not True:
                raise PermissionError('collection grant changed during read')
        return result
    finally:
        db.close()
