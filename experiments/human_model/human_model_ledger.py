"""Isolated human-model evidence-ledger experiment, not a Foundation service.

No external I/O except the explicitly supplied SQLite path. A view name is NOT
caller authentication; real process isolation and Guard policy are required
before any product integration. Source applications retain their own canon.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

KINDS = frozenset({'instruction', 'observation', 'decision', 'outcome', 'inference'})
PRIVACY = {'shareable': 0, 'restricted': 1, 'private': 2}

DDL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS evidence (
 id TEXT PRIMARY KEY,
 source_uri TEXT NOT NULL,
 source_revision TEXT NOT NULL,
 observed_at TEXT,
 captured_at TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('instruction','observation','decision','outcome','inference')),
 scope TEXT NOT NULL,
 privacy TEXT NOT NULL CHECK(privacy IN ('private','restricted','shareable')),
 content TEXT NOT NULL,
 content_sha256 TEXT NOT NULL,
 supersedes TEXT REFERENCES evidence(id),
 disputed INTEGER NOT NULL DEFAULT 0 CHECK(disputed IN (0,1)),
 UNIQUE(source_uri, source_revision, content_sha256),
 UNIQUE(supersedes)
);
CREATE TABLE IF NOT EXISTS model_views (
 id TEXT PRIMARY KEY,
 purpose TEXT NOT NULL,
 audience TEXT NOT NULL,
 allowed_scopes TEXT NOT NULL,
 max_privacy TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 0,
 stale INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS model_sources (
 model_id TEXT NOT NULL REFERENCES model_views(id),
 evidence_id TEXT NOT NULL REFERENCES evidence(id),
 PRIMARY KEY (model_id, evidence_id)
);
CREATE TABLE IF NOT EXISTS change_log (
 seq INTEGER PRIMARY KEY AUTOINCREMENT,
 evidence_id TEXT NOT NULL REFERENCES evidence(id),
 action TEXT NOT NULL,
 at TEXT NOT NULL
);
"""


def now():
    return datetime.now(timezone.utc).isoformat()


class Ledger:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path))
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript(DDL)

    @classmethod
    def open_external(cls, root, **validation_options):
        """Open SQLite on an explicitly mounted external volume; never fall back."""
        from storage_location import validated_ledger_path
        return cls(validated_ledger_path(root, **validation_options))

    def close(self):
        self.db.close()

    def add(self, *, source_uri, source_revision, kind, scope, content,
            privacy='private', observed_at=None, supersedes=None, disputed=False):
        if not all(isinstance(x, str) and x.strip() for x in
                   (source_uri, source_revision, scope, content)):
            raise ValueError('source, revision, scope and content required')
        if kind not in KINDS or privacy not in PRIVACY:
            raise ValueError('invalid evidence kind or privacy classification')
        digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
        # A source URI identifies one source record, not an entire multirow sheet.
        # Refuse two meanings for the same source revision.
        earlier = self.db.execute(
            'SELECT id,content_sha256,kind,scope,privacy,supersedes,disputed,observed_at '
            'FROM evidence WHERE source_uri=? AND source_revision=?',
            (source_uri, source_revision)
        ).fetchone()
        if earlier:
            if earlier[1:] == (digest, kind, scope, privacy, supersedes, int(disputed), observed_at):
                return earlier[0]
            raise ValueError('conflicting content or metadata for the same source revision')
        if supersedes is not None:
            old = self.db.execute('SELECT scope FROM evidence WHERE id=?', (supersedes,)).fetchone()
            if old is None or old[0] != scope:
                raise ValueError('correction must cite evidence in the identical scope')
            if self.db.execute('SELECT 1 FROM evidence WHERE supersedes=?', (supersedes,)).fetchone():
                raise ValueError('a successor already exists: reconcile before another correction')
        eid = str(uuid4())
        with self.db:
            self.db.execute(
                'INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (eid, source_uri, source_revision, observed_at, now(),
                 kind, scope, privacy, content, digest, supersedes, int(disputed))
            )
            self.db.execute('INSERT INTO change_log(evidence_id,action,at) VALUES(?,?,?)',
                            (eid, 'insert', now()))
            # Global invalidation is conservative and avoids stale cross-scope models.
            self.db.execute('UPDATE model_views SET stale=1')
        return eid

    def define_view(self, *, view_id, purpose, audience, allowed_scopes,
                    max_privacy='private'):
        if audience != 'foundation':
            raise PermissionError('external/Concept OS audiences are not implemented')
        if not all(isinstance(s, str) and s.strip() and s != '*' for s in allowed_scopes):
            raise ValueError('explicit non-wildcard scopes required')
        if not allowed_scopes or not view_id or not purpose or max_privacy not in PRIVACY:
            raise ValueError('invalid view definition')
        with self.db:
            self.db.execute(
                'INSERT INTO model_views(id,purpose,audience,allowed_scopes,max_privacy) '
                'VALUES(?,?,?,?,?)',
                (view_id, purpose, audience, json.dumps(sorted(set(allowed_scopes))), max_privacy)
            )

    def _view(self, *, view_id, scope, audience, max_privacy):
        if audience != 'foundation' or not view_id:
            raise PermissionError('explicit locally defined Foundation view required')
        row = self.db.execute(
            'SELECT audience,allowed_scopes,max_privacy,stale FROM model_views WHERE id=?',
            (view_id,)
        ).fetchone()
        if row is None or row[0] != audience or scope not in json.loads(row[1]):
            raise PermissionError('audience/scope not allowed by view')
        if max_privacy not in PRIVACY or PRIVACY[max_privacy] > PRIVACY[row[2]]:
            raise PermissionError('privacy exceeds approved view')
        if row[3]:
            raise RuntimeError('view is stale: rebuild and verify before serving')
        return row

    def rebuild_view(self, *, view_id):
        """Deterministic evidence projection; no LLM and no learned preferences."""
        row = self.db.execute(
            'SELECT audience,allowed_scopes,max_privacy FROM model_views WHERE id=?',
            (view_id,)
        ).fetchone()
        if row is None or row[0] != 'foundation':
            raise PermissionError('unknown or unsupported view')
        allowed = json.loads(row[1])
        max_level = PRIVACY[row[2]]
        with self.db:
            self.db.execute('DELETE FROM model_sources WHERE model_id=?', (view_id,))
            # A revoked or stale owner-attested source is never projected
            # back into an active view. Existing legacy ledgers that have not
            # undergone the explicit owner admission migration are unchanged.
            admission_present = self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='human_source_admissions'"
            ).fetchone() is not None
            excluded = (
                " AND NOT EXISTS (SELECT 1 FROM human_source_admissions a "
                "WHERE a.evidence_id=e.id AND a.state!='ACTIVE')"
                if admission_present else ""
            )
            rows = self.db.execute(
                "SELECT e.id,e.scope,e.privacy FROM evidence e "
                "WHERE NOT EXISTS (SELECT 1 FROM evidence n WHERE n.supersedes=e.id)"
                + excluded
            ).fetchall()
            for eid, scope, privacy in rows:
                if scope in allowed and PRIVACY[privacy] <= max_level:
                    self.db.execute('INSERT INTO model_sources VALUES (?,?)', (view_id, eid))
            self.db.execute(
                'UPDATE model_views SET revision=revision+1,stale=0 WHERE id=?', (view_id,)
            )
        return self.db.execute('SELECT revision FROM model_views WHERE id=?', (view_id,)).fetchone()[0]

    def query(self, *, view_id, scope, audience, max_privacy='private'):
        self._view(view_id=view_id, scope=scope, audience=audience, max_privacy=max_privacy)
        rows = self.db.execute("""
            SELECT e.id,e.kind,e.scope,e.content,e.source_uri,e.source_revision,
                   e.observed_at,e.privacy,e.disputed
            FROM model_sources ms JOIN evidence e ON e.id=ms.evidence_id
            WHERE ms.model_id=? AND e.scope=? ORDER BY e.observed_at,e.id
        """, (view_id, scope)).fetchall()
        fields = ('id','kind','scope','content','source_uri','source_revision',
                  'observed_at','privacy','disputed')
        return [dict(zip(fields, row)) for row in rows
                if PRIVACY[row[7]] <= PRIVACY[max_privacy]]
