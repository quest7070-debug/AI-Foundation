"""No-model, no-effect structural audit of an existing HumanModel-owned ledger.

The authenticated HumanModel host supplies an already-open SQLite connection.
This function never opens paths, creates databases, updates views, reads network,
infers personal meaning, or authorizes publication. Its receipt contains only
fixed keys, codes and counters; it cannot prove owner consent or source freshness.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

_PRIVACY = {'shareable': 0, 'restricted': 1, 'private': 2}
_REQUIRED = {'evidence', 'model_views', 'model_sources', 'change_log'}


def audit_ledger(db: sqlite3.Connection, *, record_limit: int = 5000,
                 view_limit: int = 128, link_limit: int = 20000) -> dict:
    """Audit a bounded snapshot without exposing records, paths, or evidence IDs.

    Never treat a clean structural audit as authenticated consent or a current
    source readback. Over-limit or unavailable evidence is explicitly incomplete.
    """
    for limit in (record_limit, view_limit, link_limit):
        if type(limit) is not int or not 1 <= limit <= 50000:
            raise ValueError('bounded audit limits required')
    if not isinstance(db, sqlite3.Connection):
        raise TypeError('existing SQLite connection required')
    out = {
        'status': 'UNAVAILABLE',
        'records': 0, 'views': 0, 'links': 0,
        'hash_mismatches': 0, 'missing_insert_audit': 0,
        'stale_views': 0, 'invalid_views': 0,
        'wrong_scope_or_privacy_links': 0, 'dangling_links': 0,
        'superseded_in_current_view': 0, 'disputed_in_current_view': 0,
        'inference_in_current_view': 0, 'missing_current_links': 0,
        'admitted_sources': 0, 'withdrawn_sources': 0,
        'source_stale_count': 0, 'inactive_in_current_view': 0,
        'withdrawn_in_current_view': 0, 'invalid_admission_links': 0,
        'source_identity': 'NOT_VERIFIED_BY_LEDGER',
        'actor_and_consent': 'NOT_REPRESENTED_BY_LEDGER',
        'execution_authority': False,
    }
    owns_read_transaction = False
    try:
        if not db.in_transaction:
            db.execute('BEGIN')
            owns_read_transaction = True
        if db.execute('PRAGMA quick_check(1)').fetchone() != ('ok',):
            out['status'] = 'INTEGRITY_FAILED'
            return out
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not _REQUIRED.issubset(tables):
            out['status'] = 'SCHEMA_UNAVAILABLE'
            return out
        out['records'] = db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]
        out['views'] = db.execute('SELECT COUNT(*) FROM model_views').fetchone()[0]
        out['links'] = db.execute('SELECT COUNT(*) FROM model_sources').fetchone()[0]
        if (out['records'] > record_limit or out['views'] > view_limit
                or out['links'] > link_limit):
            out['status'] = 'COVERAGE_INCOMPLETE'
            return out

        # The result stores metadata only; original text is read briefly for
        # integrity hashing and never returned, logged or copied to an index.
        records = {}
        record_digests = {}
        superseded = set()
        for (eid, kind, scope, privacy, disputed, content, digest, predecessor) in db.execute(
                 'SELECT id,kind,scope,privacy,disputed,'
                 'content,content_sha256,supersedes FROM evidence'):
            if (not isinstance(content, str) or
                    len(content.encode('utf-8')) > 131072 or
                    not isinstance(digest, str) or
                    hashlib.sha256(content.encode('utf-8')).hexdigest() != digest):
                out['hash_mismatches'] += 1
            records[eid] = (kind, scope, privacy, bool(disputed))
            record_digests[eid] = digest
            if predecessor is not None:
                superseded.add(predecessor)
        inserted = {row[0] for row in db.execute(
            "SELECT evidence_id FROM change_log WHERE action='insert'")}
        out['missing_insert_audit'] = len(set(records) - inserted)
        withdrawn = set()
        source_stale = set()
        if 'human_source_admissions' in tables:
            for (eid, source_sha, state, stamp, assurance,
                 version, record_id, record_hash) in db.execute(
                    "SELECT evidence_id,source_sha256,state,withdrawn_at,attestation,"
                    "version,source_record_id,source_record_id_sha256 "
                    "FROM human_source_admissions"):
                out['admitted_sources'] += 1
                if (eid not in records or source_sha != record_digests.get(eid)
                        or assurance != 'HOST_VERIFIED_OWNER_SOURCE'
                        or version != 2
                        or not isinstance(record_id, str)
                        or not record_id
                        or not isinstance(record_hash, str)
                        or (isinstance(record_id, str) and
                            hashlib.sha256(record_id.encode('utf-8')).hexdigest() != record_hash)
                        or state not in {'ACTIVE', 'STALE', 'WITHDRAWN'}):
                    out['invalid_admission_links'] += 1
                if state == 'STALE':
                    source_stale.add(eid)
                    out['source_stale_count'] += 1
                    if stamp is not None:
                        out['invalid_admission_links'] += 1
                if state == 'WITHDRAWN':
                    withdrawn.add(eid)
                    out['withdrawn_sources'] += 1
                    if not stamp:
                        out['invalid_admission_links'] += 1
                elif stamp is not None:
                    out['invalid_admission_links'] += 1
            # Bounded by the record_limit and the existing source FK.
            if out['admitted_sources'] > record_limit:
                out['status'] = 'COVERAGE_INCOMPLETE'
                return out
            if out['admitted_sources']:
                out['actor_and_consent'] = 'HOST_ATTESTED_NOT_INDEPENDENTLY_VERIFIED'

        views = {}
        for vid, audience, scopes_json, ceiling, revision, stale in db.execute(
                'SELECT id,audience,allowed_scopes,max_privacy,revision,stale '
                'FROM model_views'):
            if stale:
                out['stale_views'] += 1
            try:
                scopes = json.loads(scopes_json)
                valid = (audience == 'foundation' and isinstance(scopes, list)
                         and bool(scopes) and all(isinstance(s, str) and s and s != '*'
                                                  for s in scopes)
                         and ceiling in _PRIVACY and type(revision) is int
                         and (revision >= 1 or (bool(stale) and revision == 0)))
            except (TypeError, ValueError):
                valid = False
                scopes = []
            if not valid:
                out['invalid_views'] += 1
            views[vid] = (set(scopes) if valid else set(), ceiling, bool(stale), valid)

        indexed = {view_id: set() for view_id in views}
        for vid, eid in db.execute('SELECT model_id,evidence_id FROM model_sources'):
            if vid not in views or eid not in records:
                out['dangling_links'] += 1
                continue
            indexed[vid].add(eid)
            scopes, ceiling, stale, valid = views[vid]
            kind, scope, privacy, disputed = records[eid]
            if not valid or scope not in scopes or privacy not in _PRIVACY or (
                    ceiling in _PRIVACY and _PRIVACY[privacy] > _PRIVACY[ceiling]):
                out['wrong_scope_or_privacy_links'] += 1
            if not stale:
                if eid in superseded:
                    out['superseded_in_current_view'] += 1
                if disputed:
                    out['disputed_in_current_view'] += 1
                if kind == 'inference':
                    out['inference_in_current_view'] += 1
                if eid in withdrawn or eid in source_stale:
                    out['inactive_in_current_view'] += 1
                if eid in withdrawn:
                    out['withdrawn_in_current_view'] += 1

        # Fresh projections should contain the currently effective evidence
        # of the permitted scopes, never a silently incomplete subset.
        for vid, (scopes, ceiling, stale, valid) in views.items():
            if stale or not valid:
                continue
            expected = {eid for eid, (_, scope, privacy, _) in records.items()
                        if eid not in superseded and eid not in withdrawn
                        and eid not in source_stale and scope in scopes
                        and privacy in _PRIVACY
                        and _PRIVACY[privacy] <= _PRIVACY[ceiling]}
            out['missing_current_links'] += len(expected - indexed[vid])

        diagnostic = ('hash_mismatches', 'missing_insert_audit', 'invalid_views',
                      'wrong_scope_or_privacy_links', 'dangling_links',
                      'superseded_in_current_view', 'missing_current_links',
                      'withdrawn_in_current_view', 'inactive_in_current_view',
                      'invalid_admission_links')
        review = ('stale_views', 'source_stale_count',
                  'disputed_in_current_view', 'inference_in_current_view')
        out['status'] = ('STRUCTURE_INVALID' if any(out[k] for k in diagnostic)
                         else 'REVIEW_REQUIRED' if any(out[k] for k in review)
                         else 'STRUCTURE_OK_SOURCE_UNVERIFIED')
        return out
    except (sqlite3.Error, TypeError, ValueError, UnicodeError):
        # No exception prose may be copied into a public receipt.
        out['status'] = 'AUDIT_UNAVAILABLE'
        return out
    finally:
        if owns_read_transaction:
            db.rollback()
