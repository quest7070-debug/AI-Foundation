"""Synthetic-only no-model contract for HumanModel management structural audit."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from human_model_ledger import Ledger
from human_model_management_audit import audit_ledger


class ManagementAuditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.ledger = Ledger(Path(temp.name) / 'test.sqlite3')
        self.addCleanup(self.ledger.close)

    def add(self, *, scope='work', kind='instruction', disputed=False,
            predecessor=None, content='SYNTHETIC-PRIVATE-CONTENT'):
        self.n = getattr(self, 'n', 0) + 1
        return self.ledger.add(source_uri=f'synthetic:test:{self.n}',
                               source_revision='1', kind=kind, scope=scope,
                               privacy='private', content=content,
                               disputed=disputed, supersedes=predecessor)

    def view(self):
        self.ledger.define_view(view_id='work', purpose='synthetic only',
                                audience='foundation', allowed_scopes=['work'],
                                max_privacy='private')
        self.ledger.rebuild_view(view_id='work')

    def test_valid_view_is_structurally_clean_not_identity_or_consent_verified(self):
        self.add()
        self.view()
        before = self.ledger.db.total_changes
        result = audit_ledger(self.ledger.db)
        self.assertEqual(result['status'], 'STRUCTURE_OK_SOURCE_UNVERIFIED')
        self.assertEqual(result['records'], 1)
        self.assertEqual(result['actor_and_consent'], 'NOT_REPRESENTED_BY_LEDGER')
        self.assertEqual(result['source_identity'], 'NOT_VERIFIED_BY_LEDGER')
        self.assertIs(result['execution_authority'], False)
        self.assertEqual(before, self.ledger.db.total_changes)
        self.assertEqual(result, audit_ledger(self.ledger.db))
        self.assertNotIn('SYNTHETIC-PRIVATE-CONTENT', json.dumps(result))

    def test_fresh_view_includes_disputed_inference_but_audit_never_endorses(self):
        self.add(kind='inference', disputed=True)
        self.view()
        result = audit_ledger(self.ledger.db)
        self.assertEqual(result['status'], 'REVIEW_REQUIRED')
        self.assertEqual(result['inference_in_current_view'], 1)
        self.assertEqual(result['disputed_in_current_view'], 1)

    def test_new_source_marks_existing_projection_stale(self):
        self.add()
        self.view()
        self.add(content='SECOND-SYNTHETIC')
        result = audit_ledger(self.ledger.db)
        self.assertEqual(result['status'], 'REVIEW_REQUIRED')
        self.assertEqual(result['stale_views'], 1)

    def test_projection_correction_rebuild_drops_superseded(self):
        old = self.add()
        self.view()
        self.add(predecessor=old, content='NEW-SYNTHETIC')
        self.ledger.rebuild_view(view_id='work')
        result = audit_ledger(self.ledger.db)
        self.assertEqual(result['status'], 'STRUCTURE_OK_SOURCE_UNVERIFIED')
        self.assertEqual(result['superseded_in_current_view'], 0)
        self.assertEqual(result['links'], 1)

    def test_manually_reintroduced_superseded_link_is_detected(self):
        old = self.add()
        self.view()
        self.add(predecessor=old, content='REPLACEMENT')
        self.ledger.rebuild_view(view_id='work')
        with self.ledger.db:
            self.ledger.db.execute('INSERT INTO model_sources VALUES (?,?)', ('work', old))
        result = audit_ledger(self.ledger.db)
        self.assertEqual(result['status'], 'STRUCTURE_INVALID')
        self.assertEqual(result['superseded_in_current_view'], 1)

    def test_damaged_hash_is_detected_without_public_excerpt(self):
        eid = self.add()
        self.view()
        with self.ledger.db:
            self.ledger.db.execute('UPDATE evidence SET content=? WHERE id=?', ('CORRUPT-PRIVATE-TEXT', eid))
        result = audit_ledger(self.ledger.db)
        self.assertEqual(result['status'], 'STRUCTURE_INVALID')
        self.assertEqual(result['hash_mismatches'], 1)
        self.assertNotIn('CORRUPT-PRIVATE-TEXT', json.dumps(result))

    def test_out_of_scope_link_is_detected(self):
        self.add()
        out_of_scope = self.add(scope='other')
        self.view()
        with self.ledger.db:
            self.ledger.db.execute('INSERT INTO model_sources VALUES (?,?)', ('work', out_of_scope))
        result = audit_ledger(self.ledger.db)
        self.assertEqual(result['status'], 'STRUCTURE_INVALID')
        self.assertEqual(result['wrong_scope_or_privacy_links'], 1)

    def test_current_projection_missing_record_is_detected(self):
        eid = self.add()
        self.view()
        with self.ledger.db:
            self.ledger.db.execute('DELETE FROM model_sources WHERE model_id=? AND evidence_id=?', ('work', eid))
        result = audit_ledger(self.ledger.db)
        self.assertEqual(result['status'], 'STRUCTURE_INVALID')
        self.assertEqual(result['missing_current_links'], 1)

    def test_missing_change_log_is_detected(self):
        self.add()
        self.view()
        with self.ledger.db:
            self.ledger.db.execute('DELETE FROM change_log')
        result = audit_ledger(self.ledger.db)
        self.assertEqual(result['status'], 'STRUCTURE_INVALID')
        self.assertEqual(result['missing_insert_audit'], 1)

    def test_bound_limits_return_incomplete_not_safe(self):
        self.add()
        self.add(content='SECOND')
        self.view()
        result = audit_ledger(self.ledger.db, record_limit=1)
        self.assertEqual(result['status'], 'COVERAGE_INCOMPLETE')
        self.assertFalse(result['execution_authority'])
        with self.assertRaises(ValueError):
            audit_ledger(self.ledger.db, record_limit=True)

    def test_existing_owner_transaction_is_not_rolled_back(self):
        self.add()
        self.view()
        db = self.ledger.db
        db.execute('BEGIN')
        try:
            before = db.total_changes
            result = audit_ledger(db)
            self.assertEqual(result['status'], 'STRUCTURE_OK_SOURCE_UNVERIFIED')
            self.assertTrue(db.in_transaction)
            self.assertEqual(db.total_changes, before)
        finally:
            db.rollback()

    def test_missing_schema_fails_closed(self):
        empty = sqlite3.connect(':memory:')
        try:
            self.assertEqual(audit_ledger(empty)['status'], 'SCHEMA_UNAVAILABLE')
        finally:
            empty.close()


if __name__ == '__main__':
    unittest.main()
