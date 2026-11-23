"""Read-only Drive metadata inventory and restartable, source-bound polling.

Transport is supplied by the authorized owner. This module has no write method,
credential discovery, model call or assumption that a bounded connector is complete.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

FOLDER = 'application/vnd.google-apps.folder'
INBOX_ID = '12Vuz-C0YtcM9iDSriAUC_s5jtQ1Kt6pB6k70fzlYKu0'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def metadata(row):
    """Normalize raw Drive and connected-tool metadata without inventing fields."""
    if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id']:
        raise ValueError('SOURCE_ID_REQUIRED')
    def field(*names):
        return next((row[n] for n in names if row.get(n) is not None), None)
    result = dict(id=row['id'], name=field('name', 'title'),
                  mime_type=field('mimeType', 'mime_type'),
                  parents=field('parents', 'parent_ids'),
                  modified_at=field('modifiedTime', 'modified_time', 'updated_at'),
                  version=field('version'), etag=field('etag', 'ETag'),
                  content_checksum=field('md5Checksum'),
                  owners=field('owners'), permissions=field('permissions'),
                  shared=field('shared'), url=field('webViewLink', 'url'),
                  trashed=field('trashed'))
    result['permission_coverage'] = 'AVAILABLE' if result['permissions'] is not None else 'UNKNOWN'
    # Metadata fallback is NOT a document-content revision or an event history.
    result['metadata_sha256'] = digest(result)
    native = result['version'] or result['etag']
    result['revision'] = ('native:' + str(native)) if native else 'metadata:' + result['metadata_sha256']
    result['revision_quality'] = 'NATIVE' if native else 'METADATA_ONLY'
    return result


@dataclass(frozen=True)
class Page:
    items: tuple[dict, ...]
    next_cursor: str | None = None
    terminal_proven: bool = True
    new_start_cursor: str | None = None


class CursorExpired(RuntimeError):
    pass


class ReadOnlyDriveAPI:
    """GET-only raw API adapter; get(path, params) is an owner-authenticated port.

    The port must implement bounded timeouts and raise CursorExpired on HTTP 410.
    No token is discovered, copied from another application or widened here.
    """
    def __init__(self, get):
        self.get = get

    def list_children(self, folder, cursor=None):
        if not folder or any(x in folder for x in ("'", '\\', '*')):
            raise ValueError('INVALID_FOLDER_ID')
        params = {'q': "trashed = false and '" + folder + "' in parents",
                  'pageSize': 100, 'fields': 'nextPageToken,incompleteSearch,files(id,name,mimeType,parents,modifiedTime,version,md5Checksum,owners,permissions,shared,webViewLink)',
                  'supportsAllDrives': True, 'includeItemsFromAllDrives': True}
        if cursor: params['pageToken'] = cursor
        row = self.get('/drive/v3/files', params)
        if not isinstance(row.get('files'), list): raise ValueError('INVALID_PAGE')
        return Page(tuple(row['files']), row.get('nextPageToken'), not row.get('incompleteSearch', False))

    def get_metadata(self, source_id):
        if not source_id or '/' in source_id: raise ValueError('INVALID_SOURCE_ID')
        return self.get('/drive/v3/files/' + source_id,
                        {'fields': 'id,name,mimeType,parents,modifiedTime,version,md5Checksum,owners,permissions,shared,webViewLink,trashed',
                         'supportsAllDrives': True})

    def start_cursor(self):
        return self.get('/drive/v3/changes/startPageToken', {})['startPageToken']

    def changes(self, cursor):
        row = self.get('/drive/v3/changes', {'pageToken': cursor, 'pageSize': 100,
            'fields': 'nextPageToken,newStartPageToken,changes(fileId,removed,file(id,name,mimeType,parents,modifiedTime,version,md5Checksum,owners,permissions,shared,webViewLink,trashed))'})
        if not isinstance(row.get('changes'), list): raise ValueError('INVALID_CHANGES_PAGE')
        return Page(tuple(row['changes']), row.get('nextPageToken'), True, row.get('newStartPageToken'))


class DriveState:
    """Cursor/observation tables in the EXISTING Durable Work SQLite DB.

    Job claims and terminal state live only in work_steps, not in these tables.
    Owner-private metadata stays local; GitHub receives aggregates/hashes only.
    """
    def __init__(self, work_store):
        self.work = work_store
        self.path = Path(work_store.path)
        if self.path.is_symlink(): raise PermissionError('SYMLINK_STATE')
        self.path.chmod(0o600)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS klm_drive_scans(id TEXT PRIMARY KEY, roots TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS klm_drive_folders(scan TEXT, folder TEXT, cursor TEXT,
                    pages INTEGER DEFAULT 0, status TEXT, reason TEXT, PRIMARY KEY(scan,folder));
                CREATE TABLE IF NOT EXISTS klm_drive_pages(scan TEXT, folder TEXT, token TEXT,
                    receipt TEXT, PRIMARY KEY(scan,folder,token));
                CREATE TABLE IF NOT EXISTS klm_drive_seen(scan TEXT, id TEXT, fingerprint TEXT,
                    PRIMARY KEY(scan,id));
                CREATE TABLE IF NOT EXISTS klm_drive_objects(id TEXT PRIMARY KEY, body TEXT, seen REAL);
                CREATE TABLE IF NOT EXISTS klm_drive_events(event_key TEXT PRIMARY KEY, source_id TEXT,
                    revision TEXT, kind TEXT, observed REAL);
                CREATE TABLE IF NOT EXISTS klm_drive_cursors(owner_scope TEXT PRIMARY KEY, token TEXT,
                    status TEXT, updated REAL);
                CREATE TABLE IF NOT EXISTS klm_drive_intake(intake_id TEXT PRIMARY KEY, source_id TEXT,
                    source_revision TEXT, owner TEXT, privacy_scope TEXT, record_id TEXT,
                    created REAL, job_id TEXT UNIQUE, pointer TEXT);
            ''')

    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def begin_scan(self, roots, scan_id=None):
        roots = sorted(set(roots))
        if not roots or len(roots) > 32: raise ValueError('BOUNDED_ROOTS_REQUIRED')
        scan_id = scan_id or str(uuid.uuid4())
        with self.db() as db:
            old = db.execute('SELECT roots FROM klm_drive_scans WHERE id=?', (scan_id,)).fetchone()
            if old and old[0] != json.dumps(roots): raise ValueError('SCAN_SCOPE_CHANGED')
            if not old and db.execute('SELECT COUNT(*) FROM klm_drive_scans').fetchone()[0]>=1000:
                raise RuntimeError('SCAN_HISTORY_BOUND_REACHED')
            db.execute('INSERT OR IGNORE INTO klm_drive_scans VALUES(?,?,?)', (scan_id, json.dumps(roots), time.time()))
            for root in roots:
                db.execute('INSERT OR IGNORE INTO klm_drive_folders(scan,folder,status) VALUES(?,?,?)',
                           (scan_id, root, 'PENDING'))
        return scan_id

    def observe(self, row, *, db=None, kind=None):
        item = metadata(row)
        if db is None:
            with self.db() as conn: return self.observe(row, db=conn, kind=kind)
        old = db.execute('SELECT body FROM klm_drive_objects WHERE id=?', (item['id'],)).fetchone()
        previous = json.loads(old[0]) if old else None
        if previous:
            # Drive Changes may omit a field entirely. Omission is not an
            # authoritative null/delete: preserve the last observed value.
            aliases = {
                'name': ('name','title'), 'mime_type': ('mimeType','mime_type'),
                'parents': ('parents','parent_ids'),
                'modified_at': ('modifiedTime','modified_time','updated_at'),
                'version': ('version',), 'etag': ('etag','ETag'),
                'content_checksum': ('md5Checksum',), 'owners': ('owners',),
                'permissions': ('permissions',), 'shared': ('shared',),
                'url': ('webViewLink','url'), 'trashed': ('trashed',),
            }
            for key, names in aliases.items():
                if not any(name in row for name in names):
                    item[key] = previous.get(key)
            item['permission_coverage'] = 'AVAILABLE' if item['permissions'] is not None else 'UNKNOWN'
            stable = {k: v for k, v in item.items()
                      if k not in {'metadata_sha256','revision','revision_quality'}}
            item['metadata_sha256'] = digest(stable)
            native = item['version'] or item['etag']
            item['revision'] = 'native:' + str(native) if native else 'metadata:' + item['metadata_sha256']
            item['revision_quality'] = 'NATIVE' if native else 'METADATA_ONLY'
        if previous and previous['metadata_sha256'] == item['metadata_sha256']: return 'NO_CHANGE'
        event_kind = kind or ('DISCOVERED' if previous is None else
            'REVISION_CONFLICT' if previous['revision']==item['revision'] else
            'MOVED' if previous['parents'] is not None and item['parents'] is not None and previous['parents'] != item['parents'] else 'METADATA_CHANGED')
        key = digest((item['id'], item['revision'], item['metadata_sha256'], event_kind))
        if not db.execute('SELECT 1 FROM klm_drive_events WHERE event_key=?',(key,)).fetchone() and db.execute('SELECT COUNT(*) FROM klm_drive_events').fetchone()[0]>=50000:
            raise RuntimeError('EVENT_HISTORY_BOUND_REACHED')
        db.execute('INSERT OR IGNORE INTO klm_drive_events VALUES(?,?,?,?,?)',
                   (key, item['id'], item['revision'], event_kind, time.time()))
        db.execute('INSERT OR REPLACE INTO klm_drive_objects VALUES(?,?,?)',
                   (item['id'], json.dumps(item, ensure_ascii=False), time.time()))
        return event_kind

    def scan(self, api, scan_id, *, page_budget=100, folder_bound=1000):
        if not 1 <= page_budget <= 1000: raise ValueError('BOUNDED_PAGE_BUDGET_REQUIRED')
        for _ in range(page_budget):
            with self.db() as db:
                row = db.execute("SELECT * FROM klm_drive_folders WHERE scan=? AND status IN ('PENDING','RETRY','PARTIAL') ORDER BY folder LIMIT 1", (scan_id,)).fetchone()
            if row is None: break
            folder, cursor = row['folder'], row['cursor']
            try:
                page = api.list_children(folder, cursor)
                if not isinstance(page, Page): raise ValueError('PAGE_CONTRACT_REQUIRED')
                items = [metadata(x) for x in page.items]
                if len(items) > 1000: raise ValueError('PAGE_TOO_LARGE')
                with self.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    # Never overwrite a concurrently advanced checkpoint.
                    now = db.execute('SELECT * FROM klm_drive_folders WHERE scan=? AND folder=?', (scan_id, folder)).fetchone()
                    if now['cursor'] != cursor or now['pages'] != row['pages']: continue
                    tokens = {r[0] for r in db.execute('SELECT token FROM klm_drive_pages WHERE scan=? AND folder=?', (scan_id, folder))}
                    if page.next_cursor is not None and (page.next_cursor == cursor or page.next_cursor in tokens):
                        raise ValueError('REPEATED_PAGE_CURSOR')
                    for raw, item in zip(page.items, items):
                        prior = db.execute('SELECT fingerprint FROM klm_drive_seen WHERE scan=? AND id=?', (scan_id, item['id'])).fetchone()
                        if prior and prior[0] != item['metadata_sha256']: raise ValueError('REVISION_CHANGED_DURING_SCAN')
                        db.execute('INSERT OR IGNORE INTO klm_drive_seen VALUES(?,?,?)', (scan_id, item['id'], item['metadata_sha256']))
                        self.observe(raw, db=db)
                        if item['mime_type'] == FOLDER:
                            count = db.execute('SELECT COUNT(*) FROM klm_drive_folders WHERE scan=?', (scan_id,)).fetchone()[0]
                            if count >= folder_bound and not db.execute('SELECT 1 FROM klm_drive_folders WHERE scan=? AND folder=?',(scan_id,item['id'])).fetchone():
                                raise ValueError('FOLDER_BOUND_REACHED')
                            db.execute('INSERT OR IGNORE INTO klm_drive_folders(scan,folder,status) VALUES(?,?,?)', (scan_id, item['id'], 'PENDING'))
                    token = cursor or '<FIRST>'
                    db.execute('INSERT OR REPLACE INTO klm_drive_pages VALUES(?,?,?,?)', (scan_id, folder, token, digest([x['metadata_sha256'] for x in items])))
                    proven = page.terminal_proven and now['reason'] != 'TERMINAL_PAGE_UNPROVEN'
                    status = 'PENDING' if page.next_cursor else 'COMPLETE' if proven else 'UNPROVEN'
                    db.execute('UPDATE klm_drive_folders SET cursor=?,pages=pages+1,status=?,reason=? WHERE scan=? AND folder=?',
                               (page.next_cursor, status, None if proven else 'TERMINAL_PAGE_UNPROVEN', scan_id, folder))
            except Exception as exc:
                # Provider-origin ValueError messages may contain IDs, query
                # text or private API details. Persist/return only our fixed
                # structural reason codes, never arbitrary exception prose.
                known = {'SOURCE_ID_REQUIRED', 'INVALID_PAGE', 'PAGE_CONTRACT_REQUIRED',
                         'PAGE_TOO_LARGE', 'REPEATED_PAGE_CURSOR',
                         'REVISION_CHANGED_DURING_SCAN', 'FOLDER_BOUND_REACHED',
                         'INVALID_FOLDER_ID'}
                reason = (str(exc) if isinstance(exc, ValueError)
                          and str(exc) in known else type(exc).__name__)
                with self.db() as db:
                    # Retry resumes the SAME page; earlier pages and effects are retained.
                    db.execute('UPDATE klm_drive_folders SET status=?,reason=? WHERE scan=? AND folder=?', ('RETRY', reason[:100], scan_id, folder))
                break
        return self.scan_report(scan_id)

    def scan_report(self, scan_id):
        with self.db() as db:
            folders = [dict(r) for r in db.execute('SELECT * FROM klm_drive_folders WHERE scan=?', (scan_id,))]
            count = db.execute('SELECT COUNT(*) FROM klm_drive_seen WHERE scan=?', (scan_id,)).fetchone()[0]
        complete = sum(r['status'] == 'COMPLETE' for r in folders)
        return {'scan_id': scan_id, 'coverage': 'COMPLETE' if folders and complete == len(folders) else 'PARTIAL' if any(r['pages'] for r in folders) else 'UNKNOWN',
                'folders': len(folders), 'complete': complete, 'partial': len(folders)-complete,
                'objects': count, 'pages': sum(r['pages'] for r in folders), 'checkpoints': folders}

    def poll_changes(self, api, owner_scope, allowed_ids, *, page_budget=20):
        """Explicit IDs only: account-wide Changes never expands approved scope.

        Unknown IDs trigger RESCAN_REQUIRED, not automatic private-file ingestion.
        A lost cursor invalidates coverage; caller performs a new complete scan.
        """
        with self.db() as db:
            current = db.execute('SELECT token,status FROM klm_drive_cursors WHERE owner_scope=?',(owner_scope,)).fetchone()
        if current is None:
            token = api.start_cursor()
            with self.db() as db: db.execute('INSERT INTO klm_drive_cursors VALUES(?,?,?,?)',(owner_scope, token, 'RESCAN_REQUIRED', time.time()))
            return 'RESCAN_REQUIRED'  # no silent gap before first cursor
        if current['status'] == 'RESCAN_REQUIRED': return 'RESCAN_REQUIRED'
        token = current['token']
        visited = set()
        for _ in range(page_budget):
            try: page = api.changes(token)
            except CursorExpired:
                with self.db() as db: db.execute('UPDATE klm_drive_cursors SET status=? WHERE owner_scope=?',('RESCAN_REQUIRED',owner_scope))
                return 'RESCAN_REQUIRED'
            except Exception: return 'PARTIAL'
            if not page.terminal_proven: return 'PARTIAL'
            rescan = False
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                active=db.execute('SELECT token FROM klm_drive_cursors WHERE owner_scope=?',(owner_scope,)).fetchone()[0]
                if active != token: return 'PARTIAL'
                for event in page.items:
                    if type(event) is not dict:
                        rescan = True
                        continue
                    sid = event.get('fileId')
                    if type(sid) is not str or sid not in allowed_ids:
                        rescan = True
                        continue
                    removed = event.get('removed')
                    if removed is not None and type(removed) is not bool:
                        rescan = True
                        continue
                    if removed is True:
                        # Removal may mean deletion OR permission loss. Do not label deleted.
                        rev = 'removed:' + digest((token, sid))
                        db.execute('INSERT OR IGNORE INTO klm_drive_events VALUES(?,?,?,?,?)',(digest((sid,rev)),sid,rev,'REMOVED_OR_INACCESSIBLE',time.time()))
                    else:
                        # Changes fileId is the scoped identity. Never let an
                        # inconsistent embedded file.id expand the observed
                        # source set or let missing metadata advance CURRENT.
                        item = event.get('file')
                        if type(item) is not dict or item.get('id') != sid:
                            rescan = True
                            continue
                        self.observe(item, db=db)
                nxt = page.next_cursor or page.new_start_cursor
                if not nxt or nxt in visited or nxt == token: return 'PARTIAL'
                db.execute('UPDATE klm_drive_cursors SET token=?,status=?,updated=? WHERE owner_scope=?',
                           (nxt, 'RESCAN_REQUIRED' if rescan else 'PENDING' if page.next_cursor else 'CURRENT', time.time(), owner_scope))
            if rescan: return 'RESCAN_REQUIRED'
            if not page.next_cursor: return 'COMPLETE'
            visited.add(token); token = nxt
        return 'PARTIAL'

    def finish_resync(self, api, owner_scope, scan_id, *, start_cursor):
        """Finalize the *inventory*, not the complete change history.

        Even with a COMPLETE folder traversal, changes may have occurred after
        the pre-scan token was issued. Only poll_changes() consuming a proven
        terminal changes page may transition this owner cursor to CURRENT.
        """
        if self.scan_report(scan_id)['coverage'] != 'COMPLETE': return 'PARTIAL'
        if not isinstance(start_cursor, str) or not start_cursor:
            raise ValueError('PRE_SCAN_CURSOR_REQUIRED')
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO klm_drive_cursors VALUES(?,?,?,?)',
                       (owner_scope, start_cursor, 'PENDING', time.time()))
        return 'REPLAY_REQUIRED'

    def missing_candidates(self, before_ids, scan_id):
        with self.db() as db: seen={r[0] for r in db.execute('SELECT id FROM klm_drive_seen WHERE scan=?',(scan_id,))}
        status='MISSING_FROM_SCOPE_NOT_PROVEN_DELETED' if self.scan_report(scan_id)['coverage']=='COMPLETE' else 'UNKNOWN_COVERAGE'
        return [{'source_id': sid, 'status': status} for sid in sorted(set(before_ids)-seen)]
