"""Host callback acceptance, using native-shaped ports; no external services."""
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.klm_drive_input import DriveState, Page, CursorExpired, INBOX_ID
from ai_foundation.klm_drive_cycle import NativeDriveCycle, NativeInboxReader
from ai_foundation.klm_drive_runtime import OwnerInboxHTTP
from ai_foundation.orchestration import WorkStatus


class Busy(Exception):
    pass


class Lease:
    held = False
    busy = False

    @contextmanager
    def hold(self, *, max_wait_s):
        if self.busy:
            raise Busy()
        assert max_wait_s == 0 and not self.held
        self.held = True
        try:
            yield
        finally:
            self.held = False


class Drive:
    def __init__(self):
        self.calls = []
        self.pages = {None: Page(({'id': 'file', 'mimeType': 'text/plain', 'version': '1'},))}
        self.events = {'before': Page((), new_start_cursor='after'),
                       'after': Page((), new_start_cursor='next')}

    def start_cursor(self):
        self.calls.append('start')
        return 'before'

    def list_children(self, root, cursor):
        self.calls.append(('list', root, cursor))
        return self.pages[cursor]

    def changes(self, cursor):
        self.calls.append(('changes', cursor))
        result = self.events[cursor]
        if isinstance(result, Exception):
            raise result
        return result


class CycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = DriveState(SQLiteWorkStore(Path(self.tmp.name) / 'work.db'))
        self.lease = Lease()
        self.api = Drive()
        self.now = 1000
        self.rows = [['header'], ['PRIVATE_CELLS_NEVER_IN_DB']]
        self.grid = {'rowCount': 100, 'columnCount': 12}
        self.reads = []
        self.inbox = NativeInboxReader(self.get)
        self.cycle = self.make_cycle()

    def get(self, path, params):
        self.reads.append(path)
        if '/values/' in path:
            return {'values': self.rows}
        return {'sheets': [{'properties': {'title': 'Inbox', 'gridProperties': self.grid}}]}

    def make_cycle(self):
        return NativeDriveCycle(self.state, roots=['root'], owner_scope='owner',
                                drive=self.api, inbox=self.inbox, clock=lambda: self.now)

    def saved(self):
        with self.state.db() as db:
            return dict(db.execute('SELECT * FROM klm_drive_native_cycle').fetchone())

    def test_poll_failure_exposes_only_pinned_transport_error_code(self):
        def failed_transport():
            raise RuntimeError('DRIVE_HTTP_403')
        self.inbox.values = failed_transport
        result = self.cycle.tick()
        self.assertEqual(result['status'], 'POLL_FAILED')
        self.assertEqual(result['error_type'], 'RuntimeError')
        self.assertEqual(result['poll_error_code'], 'DRIVE_HTTP_403')
        self.now += 900
        def private_failure():
            raise RuntimeError('PRIVATE_KEY https://private/source')
        self.inbox.values = private_failure
        hidden = self.cycle.tick()
        self.assertEqual(hidden['poll_error_code'], 'UNCLASSIFIED')
        self.assertNotIn('PRIVATE_KEY', json.dumps(hidden))

    def test_multiple_due_cycles_resume_cursor_and_deduplicate_after_restart(self):
        first = self.cycle.tick()
        self.assertEqual((first['status'], first['staged']), ('CURRENT', 1))
        before = len(self.reads)
        self.assertEqual(self.make_cycle().tick()['status'], 'NOT_DUE')
        self.assertEqual(before, len(self.reads))
        self.now += 900
        result = self.make_cycle().tick()
        self.assertEqual((result['status'], result['duplicates']), ('CURRENT', 1))
        self.assertEqual(self.api.calls.count('start'), 1)
        self.assertEqual(self.api.calls[-1], ('changes', 'after'))
        self.assertNotIn(b'PRIVATE_CELLS_NEVER_IN_DB', self.state.path.read_bytes())

    def test_partial_files_list_preserves_pre_scan_token_and_page_on_restart(self):
        self.api.pages[None] = Page((), 'second')
        self.api.pages['second'] = Page(())
        self.assertEqual(self.cycle.tick(page_budget=1)['status'], 'RESYNC_PARTIAL')
        self.assertEqual(self.saved()['pre_token'], 'before')
        self.assertNotIn(('changes', 'before'), self.api.calls)
        self.now += 900
        self.assertEqual(self.make_cycle().tick(page_budget=1)['status'], 'CURRENT')
        self.assertEqual(self.api.calls.count(('list', 'root', None)), 1)

    def test_failed_changes_is_never_current_and_next_tick_replays_same_token(self):
        self.api.events['before'] = OSError('secret-access-token')
        result = self.cycle.tick()
        self.assertEqual(result['status'], 'REPLAY_PARTIAL')
        self.assertIsNone(self.saved()['last_current'])
        with self.state.db() as db:
            self.assertEqual(db.execute('SELECT status FROM klm_drive_cursors').fetchone()[0], 'PENDING')
        self.now += 900
        self.api.events['before'] = Page((), new_start_cursor='after')
        self.assertEqual(self.make_cycle().tick()['status'], 'CURRENT')
        self.assertEqual(self.api.calls.count(('changes', 'before')), 2)
        self.assertNotIn('secret', json.dumps(result))

    def test_changes_page_budget_survives_restart_without_reset_to_pre_scan_token(self):
        self.api.events['before'] = Page((), 'middle')
        self.api.events['middle'] = Page((), new_start_cursor='after')
        self.assertEqual(self.cycle.tick(page_budget=1)['status'], 'REPLAY_PARTIAL')
        self.now += 900
        self.assertEqual(self.make_cycle().tick(page_budget=1)['status'], 'CURRENT')
        self.assertEqual(self.api.calls.count(('changes', 'before')), 1)

    def test_previous_current_is_not_reused_after_a_new_poll_fails(self):
        self.assertEqual(self.cycle.tick()['status'], 'CURRENT')
        previous = self.saved()['last_current']
        self.now += 900
        self.api.events['after'] = OSError()
        self.assertEqual(self.make_cycle().tick()['status'], 'REPLAY_PARTIAL')
        self.assertEqual(self.saved()['last_current'], previous)
        with self.state.db() as db:
            self.assertEqual(db.execute('SELECT status FROM klm_drive_cursors').fetchone()[0], 'PENDING')

    def test_conflicting_scan_is_restarted_instead_of_retrying_the_old_page_forever(self):
        self.api.pages[None] = Page(({'id': 'file', 'version': '1'},), 'second')
        self.api.pages['second'] = Page(({'id': 'file', 'version': '2'},))
        self.assertEqual(self.cycle.tick()['status'], 'RESYNC_PARTIAL')
        self.assertIsNone(self.saved()['scan_id'])
        self.now += 900
        self.api.pages[None] = Page(({'id': 'file', 'version': '2'},))
        self.assertEqual(self.make_cycle().tick()['status'], 'CURRENT')
        self.assertEqual(self.api.calls.count('start'), 2)

    def test_expired_cursor_and_unknown_new_id_require_a_new_scoped_scan(self):
        for event in [CursorExpired(), Page(({'fileId': 'foreign', 'file': {'id': 'foreign'}},), new_start_cursor='after')]:
            with self.subTest(event=event):
                self.api.events['before'] = event
                self.assertEqual(self.make_cycle().tick()['status'], 'RESCAN_REQUIRED')
                self.assertIsNone(self.saved()['scan_id'])
                with self.state.db() as db:
                    self.assertIsNone(db.execute("SELECT id FROM klm_drive_objects WHERE id='foreign'").fetchone())
                self.now += 900
        self.assertEqual(self.api.calls.count('start'), 2)

    def test_complete_rescan_can_stage_exact_research_but_cannot_infer(self):
        # The account-wide Changes cursor is no longer complete, yet the
        # bounded root inventory finished. The research reader is responsible
        # for exact owner/root/file/media verification before enqueue.
        staged = []
        class Research:
            def stage_one(self, state, queue):
                self_state = state
                staged.append((self_state is self_test.state, queue.state is self_test.state))
                return 'STAGED'

        class Worker:
            calls = 0
            def tick(self, *, read_source, handler):
                self.calls += 1
                return 'SHOULD_NOT_RUN'

        self_test = self
        worker = Worker()
        self.api.events['before'] = CursorExpired()
        cycle = NativeDriveCycle(
            self.state, roots=['root'], owner_scope='owner', drive=self.api,
            inbox=self.inbox, research_reader=Research(), clock=lambda: self.now)
        result = cycle.tick(worker=worker)
        self.assertEqual(result['status'], 'RESCAN_REQUIRED')
        self.assertEqual(result['research_intake'], 'STAGED')
        self.assertEqual(staged, [(True, True)])
        self.assertEqual(worker.calls, 0)
        self.assertIsNone(self.saved()['scan_id'])

    def test_incomplete_research_scan_never_stages_or_infers(self):
        class Research:
            calls = 0
            def stage_one(self, state, queue):
                self.calls += 1
                return 'STAGED'

        class Worker:
            calls = 0
            def tick(self, *, read_source, handler):
                self.calls += 1
                return 'SHOULD_NOT_RUN'

        self.api.pages[None] = Page((), 'second')
        self.api.pages['second'] = Page(())
        reader, worker = Research(), Worker()
        cycle = NativeDriveCycle(
            self.state, roots=['root'], owner_scope='owner', drive=self.api,
            inbox=self.inbox, research_reader=reader, clock=lambda: self.now)
        result = cycle.tick(page_budget=1, worker=worker)
        self.assertEqual(result['status'], 'RESYNC_PARTIAL')
        self.assertNotIn('research_intake', result)
        self.assertEqual(reader.calls, 0)
        self.assertEqual(worker.calls, 0)

    def test_existing_sync_claim_does_not_read_or_consume_tick_or_replay_after_restart(self):
        self.state.work.claim_not_running(self.cycle.job_id, 0)
        self.assertEqual(self.make_cycle().tick()['status'], 'SYNC_ACTIVE_OR_RECONCILE_REQUIRED')
        self.assertEqual(self.reads, [])
        self.assertIsNone(self.saved()['last_tick'])

    def test_metadata_never_holds_compute_lease_and_worker_still_checks_dev_priority(self):
        parent = self
        class Worker:
            calls = 0
            def tick(self, *, read_source, handler):
                parent.assertFalse(parent.lease.held)
                parent.assertEqual(parent.state.work.load(parent.cycle.job_id)[0].status.value, 'PLANNED')
                self.calls += 1
                return 'WAIT_DEV_IDLE'
        worker = Worker()
        self.api.events['before'] = OSError()
        self.assertEqual(self.cycle.tick(worker=worker)['status'], 'REPLAY_PARTIAL')
        self.assertEqual(worker.calls, 0)
        self.now += 900
        self.api.events['before'] = Page((), new_start_cursor='after')
        self.assertEqual(self.cycle.tick(worker=worker)['inference'], 'WAIT_DEV_IDLE')
        self.assertEqual(worker.calls, 1)

    def test_metadata_does_not_block_on_busy_compute_and_overlapping_sync_defers(self):
        self.lease.busy = True  # not consulted: metadata uses no compute lease
        original = self.get
        nested = []
        def get(path, params):
            nested.append(self.make_cycle().tick()['status'])
            return original(path, params)
        self.inbox.get = get
        self.assertEqual(self.cycle.tick()['status'], 'CURRENT')
        self.assertEqual(set(nested), {'SYNC_ACTIVE_OR_RECONCILE_REQUIRED'})

    def test_poll_finalizer_does_not_rewind_concurrent_verified_step(self):
        # Another owner-bound reconciler may finalize the shared Work step
        # while this tick is in a read-only provider callback.
        def observe_concurrent_completion(page_budget):
            self.assertEqual(self.state.work.load(self.cycle.job_id)[0].status,
                             WorkStatus.RUNNING)
            self.state.work.transition(self.cycle.job_id, 0, WorkStatus.RUNNING,
                                       WorkStatus.VERIFIED, 'INDEPENDENT_RECONCILIATION')
            return self.cycle._report('CURRENT')

        self.cycle._poll = observe_concurrent_completion
        self.assertEqual(self.cycle.tick()['status'], 'CURRENT')
        step = self.state.work.load(self.cycle.job_id)[0]
        self.assertEqual(step.status, WorkStatus.VERIFIED)
        self.assertEqual(step.result, 'INDEPENDENT_RECONCILIATION')
        self.assertEqual(self.cycle.tick()['status'], 'SYNC_ACTIVE_OR_RECONCILE_REQUIRED')

    def test_inbox_grid_growth_fails_without_accepting_a_truncated_prefix(self):
        for grid in [{'rowCount': 1001, 'columnCount': 12}, {'rowCount': 100, 'columnCount': 13}]:
            self.grid = grid
            self.assertEqual(self.cycle.tick()['status'], 'POLL_FAILED')
            self.assertFalse(any('/values/' in p for p in self.reads))
            self.assertEqual(self.api.calls, [])
            self.now += 900

    def test_inbox_source_uses_fresh_cells_and_foreign_resource_is_rejected(self):
        from ai_foundation.klm_drive_work import inbox_records
        pointer = inbox_records(self.rows, owner='owner')[0]
        self.assertEqual(self.inbox.source(pointer)['revision'], pointer['source_revision'])
        self.rows[1][0] = 'changed'
        self.assertEqual(self.inbox.source(pointer)['revision'], 'ROW_MISSING_CHANGED_OR_AMBIGUOUS')
        with self.assertRaises(PermissionError):
            self.inbox.source({**pointer, 'source_id': 'foreign'})

    def test_readonly_http_port_cannot_address_other_sheets_or_drive_paths(self):
        port = OwnerInboxHTTP(lambda: self.fail('rejected paths must not request a token'))
        for path in ['/drive/v3/files', '/v4/spreadsheets/foreign',
                     '/v4/spreadsheets/' + INBOX_ID + '/values/Other!A1:L100']:
            with self.assertRaises(PermissionError):
                port(path, {})

    def test_calendar_month_rescan_reuses_existing_cycle_and_keeps_work(self):
        from datetime import datetime, timezone
        self.now = datetime(2026, 11, 8, tzinfo=timezone.utc).timestamp()
        self.assertEqual(self.cycle.tick()['status'], 'CURRENT')
        before = len(self.api.calls)
        self.now = datetime(2026, 12, 1, tzinfo=timezone.utc).timestamp()
        self.assertEqual(self.cycle.tick()['status'], 'CURRENT')
        self.assertIn('start', self.api.calls[before:])
        self.assertEqual(self.state.work.load(self.cycle.job_id)[0].status.value, 'PLANNED')
        self.now += 900
        self.api.events['next'] = Page((), new_start_cursor='later')
        self.assertEqual(self.cycle.tick()['status'], 'CURRENT')
        self.assertEqual(self.api.calls.count('start'), 2)

    def test_invalid_clock_cannot_poison_persisted_tick_or_request_drive(self):
        for clock in (float('nan'), float('inf'), -1, 10**30, 10**400, 'untrusted', True):
            with self.subTest(clock=str(clock)):
                self.now = clock
                self.assertEqual(self.make_cycle().tick()['status'],
                                 'CLOCK_RECONCILE_REQUIRED')
                self.assertIsNone(self.saved()['last_tick'])
                self.assertEqual(self.reads, [])
                self.assertEqual(self.api.calls, [])
        self.now = 1000
        self.assertEqual(self.make_cycle().tick()['status'], 'CURRENT')
        saved = self.saved()['last_tick']
        self.now = float('nan')
        self.assertEqual(self.make_cycle().tick()['status'],
                         'CLOCK_RECONCILE_REQUIRED')
        self.assertEqual(self.saved()['last_tick'], saved)

    def test_clock_regression_never_advances_external_polling(self):
        self.cycle.tick()
        before = len(self.reads)
        self.now = 1
        self.assertEqual(self.cycle.tick()['status'], 'CLOCK_RECONCILE_REQUIRED')
        self.assertEqual(len(self.reads), before)

    def test_sheets_transport_uses_official_origin_get_and_bounded_read(self):
        from io import BytesIO
        calls = []
        class Reply(BytesIO):
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.close()
        class Opener:
            def open(self, req, timeout):
                calls.append((req.full_url, req.method, timeout))
                return Reply(b'{"sheets":[]}')
        port = OwnerInboxHTTP(lambda: 'test-only-not-a-real-token')
        port.opener = Opener()
        self.assertEqual(port('/v4/spreadsheets/' + INBOX_ID, {}), {'sheets': []})
        self.assertTrue(calls[0][0].startswith('https://sheets.googleapis.com/v4/'))
        self.assertEqual(calls[0][1:], ('GET', 10))


if __name__ == '__main__':
    unittest.main()

