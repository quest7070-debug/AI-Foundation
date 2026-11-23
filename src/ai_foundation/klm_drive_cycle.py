"""Restartable native Drive/Inbox tick for the existing host scheduler.

Authenticated ports are supplied explicitly by the existing host. This module
does not discover credentials, register a timer, start a model, or write Drive.
"""
from __future__ import annotations

import math
import re
import time
from datetime import datetime, timezone

from .klm_drive_input import INBOX_ID, digest
from .klm_drive_work import IntakeQueue, inbox_records, read_inbox_source
from .orchestration import WorkStatus


# Only these literal transport / state codes may leave the owner host.
# Exception text can contain OAuth responses, source paths or private cells.
POLL_ERROR_CODES = frozenset({
    "DRIVE_AUTH_REQUIRED", "OAUTH_TRANSPORT_OR_REPLY_INVALID",
    "RESYNC_REPLAY_CONTRACT_REQUIRED", "RESYNC_CURSOR_MISSING",
    *("OAUTH_HTTP_" + str(status) for status in
      (400, 401, 403, 429, 500, 502, 503, 504)),
    *("DRIVE_HTTP_" + str(status) for status in
      (400, 401, 403, 404, 408, 409, 410, 429, 500, 502, 503, 504)),
})

class NativeInboxReader:
    """Read the exact existing Inbox through an authenticated GET-only Sheets port.

    Read grid metadata each time; never assume the original 100 rows still fit.
    No prefix is accepted as the full source if the grid has grown beyond bounds.
    """
    def __init__(self, get):
        self.get = get

    def values(self):
        base = '/v4/spreadsheets/' + INBOX_ID
        meta = self.get(base, {'fields': 'sheets(properties(title,gridProperties))'})
        sheets = [s['properties'] for s in meta['sheets']
                  if s.get('properties', {}).get('title') == 'Inbox']
        if len(sheets) != 1:
            raise ValueError('EXACT_INBOX_TAB_REQUIRED')
        grid = sheets[0]['gridProperties']
        rows, cols = grid['rowCount'], grid['columnCount']
        if (type(rows) is not int or type(cols) is not int
                or not 1 <= rows <= 1000 or not 1 <= cols <= 12):
            raise ValueError('INBOX_GRID_OUT_OF_BOUND')
        result = self.get(base + '/values/Inbox!A1:L' + str(rows),
                          {'valueRenderOption': 'FORMATTED_VALUE', 'majorDimension': 'ROWS'})
        values = result.get('values', [])
        if (not isinstance(values, list) or len(values) > rows
                or any(not isinstance(r, list) or len(r) > 12 for r in values)):
            raise ValueError('INVALID_INBOX_VALUES')
        return values, rows

    def source(self, pointer):
        values, rows = self.values()
        return read_inbox_source(pointer, lambda *args: {'values': values}, allocated_rows=rows)


class NativeDriveCycle:
    """One due tick, resumable across invocations; no new scheduler/work DB.

    Existing Durable Work claims serialize metadata callbacks without holding
    the host COMPUTE lease during network I/O. IdleKlmWorker alone acquires that
    shared compute lease for inference. Every tick reads fresh Inbox cells;
    only identity/hash pointers are persisted. Interrupted claims need reconciliation.
    """
    def __init__(self, state, *, roots, owner_scope, drive, inbox, research_reader=None, clock=time.time):
        roots = sorted(set(roots))
        if (not 1 <= len(roots) <= 32 or not isinstance(owner_scope, str)
                or not 1 <= len(owner_scope) <= 256
                or any(not isinstance(r, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', r)
                       for r in roots)):
            raise ValueError('EXPLICIT_BOUNDED_SCOPE_REQUIRED')
        self.state = state
        self.roots = roots
        self.owner = owner_scope
        self.api = drive
        self.inbox = inbox
        self.research_reader = research_reader
        self.clock = clock
        self.key = digest((owner_scope, roots))
        self.job_id = 'klm-native-poll:' + self.key
        with state.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE IF NOT EXISTS klm_drive_native_cycle(
                scope TEXT PRIMARY KEY, scan_id TEXT, pre_token TEXT,
                last_tick REAL, last_current REAL)''')
            if 'inventory_month' not in {r[1] for r in db.execute('PRAGMA table_info(klm_drive_native_cycle)')}:
                db.execute('ALTER TABLE klm_drive_native_cycle ADD COLUMN inventory_month TEXT')
            if (not db.execute('SELECT 1 FROM klm_drive_native_cycle WHERE scope=?', (self.key,)).fetchone()
                    and db.execute('SELECT COUNT(*) FROM klm_drive_native_cycle').fetchone()[0] >= 32):
                raise RuntimeError('NATIVE_SCOPE_HISTORY_BOUND_REACHED')
            db.execute('INSERT OR IGNORE INTO klm_drive_native_cycle(scope) VALUES(?)', (self.key,))
        self.state.work.ensure(self.job_id, ['native-metadata-poll'])

    def tick(self, *, page_budget=20, worker=None, handler=None, read_source=None):
        if type(page_budget) is not int or not 1 <= page_budget <= 100:
            raise ValueError('BOUNDED_PAGE_BUDGET_REQUIRED')
        if not self.state.work.claim_not_running(self.job_id, 0):
            return self._report('SYNC_ACTIVE_OR_RECONCILE_REQUIRED')
        try:
            try:
                result = self._poll(page_budget)
            except Exception as exc:
                # An actionable fixed transport code is safe to retain;
                # arbitrary provider/Keychain/private exception text is not.
                code = str(exc) if type(exc) is RuntimeError else ""
                result = self._report(
                    'POLL_FAILED', error_type=type(exc).__name__,
                    poll_error_code=code if code in POLL_ERROR_CODES else "UNCLASSIFIED")
        finally:
            # A killed process cannot reach this: its existing RUNNING claim is
            # preserved rather than resetting a possibly active callback.
            # Release only the RUNNING claim owned by this tick. A concurrent
            # cancellation/reconciliation may already have changed this step;
            # never rewind a newer terminal or owner decision to PLANNED.
            self.state.work.transition(self.job_id, 0, WorkStatus.RUNNING,
                                       WorkStatus.PLANNED)
        # A RESCAN_REQUIRED result is only returned *after* a COMPLETE
        # owner-root inventory, when the separate account-wide Changes replay
        # encounters an unknown or expired cursor. That cannot certify the
        # global KLM inventory as CURRENT, but it need not strand an already
        # scanned research note: stage_one independently re-reads the exact
        # app-owned file metadata, approved parent and SHA-256 media before
        # creating its existing idempotent Durable Work pointer.
        # Never stage after a partial inventory, and never run inference while
        # Changes is unverified.
        if (result['status'] in {'CURRENT', 'RESCAN_REQUIRED'}
                and self.research_reader is not None):
            try:
                result['research_intake'] = self.research_reader.stage_one(
                    self.state, IntakeQueue(self.state))
            except Exception:
                # Failed research intake must not disrupt normal owner Inbox,
                # KLM scan, existing 9B claims, or risk logging source data.
                result['research_intake'] = 'REVIEW_REQUIRED'
        if worker is not None and result['status'] == 'CURRENT':
            result['inference'] = worker.tick(
                read_source=read_source or self.inbox.source, handler=handler)
        return result

    def _report(self, status, **values):
        return {'status': status, 'execution_authority': False,
                'inbox_writes': 0, 'next_poll_seconds': 900, **values}

    def _poll(self, page_budget):
        now = self.clock()
        # Reject an impossible/untrusted clock *before* persisting last_tick.
        # NaN is stored as NULL by SQLite and a far-future finite timestamp
        # can permanently strand later real ticks in CLOCK_RECONCILE_REQUIRED.
        if type(now) not in (int, float) or now < 0:
            return self._report('CLOCK_RECONCILE_REQUIRED')
        try:
            # math.isfinite converts integers to float; oversized integer
            # clocks can raise OverflowError before datetime validation.
            if not math.isfinite(now):
                return self._report('CLOCK_RECONCILE_REQUIRED')
            month = datetime.fromtimestamp(now, timezone.utc).strftime('%Y-%m')
        except (OverflowError, ValueError, OSError):
            return self._report('CLOCK_RECONCILE_REQUIRED')
        with self.state.db() as db:
            saved = dict(db.execute('SELECT * FROM klm_drive_native_cycle WHERE scope=?',
                                     (self.key,)).fetchone())
            if saved['last_tick'] is not None:
                elapsed = now - saved['last_tick']
                if elapsed < 0:
                    return self._report('CLOCK_RECONCILE_REQUIRED')
                if elapsed < 900:
                    return self._report('NOT_DUE')
            # Record the attempt before any external call. Failures are rate-bounded.
            db.execute('UPDATE klm_drive_native_cycle SET last_tick=? WHERE scope=?', (now, self.key))

        # An authenticated Inbox failure cannot silently substitute old cells.
        values, _ = self.inbox.values()
        queue = IntakeQueue(self.state)
        outcomes = [queue.enqueue(p) for p in inbox_records(values, owner=self.owner)]
        scan = saved['scan_id']
        pre_token = saved['pre_token']
        if saved['inventory_month'] != month and saved['last_current'] is not None:
            # One rescan per calendar month, using existing page checkpoints.
            # Persist the reset before network I/O; interruptions resume it.
            with self.state.db() as db:
                db.execute('UPDATE klm_drive_native_cycle SET scan_id=NULL,pre_token=NULL,last_current=NULL WHERE scope=?',
                           (self.key,))
            scan = pre_token = None
        if scan is None:
            # Capture BEFORE the scan and persist before consuming the first page.
            pre_token = self.api.start_cursor()
            if not isinstance(pre_token, str) or not 1 <= len(pre_token) <= 4096:
                raise ValueError('PRE_SCAN_TOKEN_REQUIRED')
            scan = self.state.begin_scan(self.roots)
            with self.state.db() as db:
                db.execute('UPDATE klm_drive_native_cycle SET scan_id=?,pre_token=? WHERE scope=?',
                           (scan, pre_token, self.key))
        report = self.state.scan(self.api, scan, page_budget=page_budget)
        counts = {key: report[key] for key in ('coverage', 'folders', 'objects', 'pages')}
        counts.update(staged=outcomes.count('STAGED'), duplicates=outcomes.count('ALREADY_STAGED'))
        if report['coverage'] != 'COMPLETE':
            # A revision conflict cannot be repaired by replaying the same old
            # scan page; start a fresh bounded resync at the next due tick.
            if any(r['reason'] in {'REVISION_CHANGED_DURING_SCAN', 'REPEATED_PAGE_CURSOR', 'CursorExpired'}
                   for r in report['checkpoints']):
                with self.state.db() as db:
                    db.execute('UPDATE klm_drive_native_cycle SET scan_id=NULL,pre_token=NULL WHERE scope=?',
                               (self.key,))
            return self._report('RESYNC_PARTIAL', **counts)

        # #284: completing files.list is NOT proof that Changes is current.
        # Do not reset the token on a resumed multi-page replay.
        with self.state.db() as db:
            cursor = db.execute('SELECT token,status FROM klm_drive_cursors WHERE owner_scope=?',
                                (self.key,)).fetchone()
            allowed = {r[0] for r in db.execute('SELECT id FROM klm_drive_seen WHERE scan=?', (scan,))}
        allowed.update(self.roots)
        if pre_token is not None:
            outcome = self.state.finish_resync(self.api, self.key, scan, start_cursor=pre_token)
            if outcome != 'REPLAY_REQUIRED':
                raise RuntimeError('RESYNC_REPLAY_CONTRACT_REQUIRED')
            with self.state.db() as db:
                db.execute('UPDATE klm_drive_native_cycle SET pre_token=NULL WHERE scope=?', (self.key,))
        elif cursor is None:
            raise RuntimeError('RESYNC_CURSOR_MISSING')
        # A previous successful poll does not certify this new invocation.
        with self.state.db() as db:
            db.execute("UPDATE klm_drive_cursors SET status='PENDING' WHERE owner_scope=? AND status='CURRENT'",
                       (self.key,))
        changes = self.state.poll_changes(self.api, self.key, allowed, page_budget=page_budget)
        if changes == 'RESCAN_REQUIRED':
            with self.state.db() as db:
                db.execute('UPDATE klm_drive_native_cycle SET scan_id=NULL,pre_token=NULL WHERE scope=?',
                           (self.key,))
            return self._report('RESCAN_REQUIRED', changes=changes, **counts)
        if changes != 'COMPLETE':
            return self._report('REPLAY_PARTIAL', changes=changes, **counts)
        with self.state.db() as db:
            db.execute('UPDATE klm_drive_native_cycle SET last_current=?,inventory_month=? WHERE scope=?', (now, month, self.key))
        return self._report('CURRENT', changes=changes, **counts)

