"""Synthetic, no-provider acceptance for exact owner-source admission."""
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from human_model_ledger import Ledger
from human_model_source_admission import (
    HostCollectionGrant, TrustedSourceSnapshot, verify_source_admission,
    stage_exact_source,
)

TEXT = "PRIVATE-SYNTHETIC-USER-UTTERANCE"


class HumanModelSourceAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = Ledger(Path(self.temp.name) / "test.sqlite3")
        self.addCleanup(self.ledger.close)
        self.grant = HostCollectionGrant(
            owner_id="host-user", source_system="chat",
            source_record_id="message-1", source_revision="rev-1",
            source_uri="chat:synthetic:thread-1/message-1",
            scope="work", privacy="private", purpose="owner-evidence",
            consent_id="test-owner-consent", consent_revision="1",
            expected_sha256=hashlib.sha256(TEXT.encode()).hexdigest(),
        )
        self.snapshot = TrustedSourceSnapshot(
            source_system=self.grant.source_system,
            source_record_id=self.grant.source_record_id,
            source_revision=self.grant.source_revision,
            source_uri=self.grant.source_uri,
            actor_principal_id="host-user", actor_kind="owner",
            actor_verified=True, complete=True, content=TEXT,
            observed_at="2026-11-10T12:30:00+09:00",
        )

    def verify(self, grant=None, snapshot=None, **kw):
        return verify_source_admission(
            self.grant if grant is None else grant,
            self.snapshot if snapshot is None else snapshot,
            current_authenticated_owner=kw.get("owner", "host-user"),
            grant_verifier=kw.get("verifier", lambda _: True),
        )

    def test_observation_is_not_an_authorized_person_fact(self):
        candidate = self.verify()
        self.assertEqual(candidate.content, TEXT)
        safe = candidate.safe_receipt()
        self.assertEqual(safe["kind"], "observation")
        self.assertFalse(safe["person_fact_approved"])
        self.assertFalse(safe["execution_authority"])
        self.assertNotIn(TEXT, json.dumps(safe))
        self.assertNotIn(self.grant.source_uri, json.dumps(safe))
        self.assertEqual(self.ledger.db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0], 0)

    def test_very_same_snapshot_rechecked_without_ledger_write(self):
        calls = []
        def reader(system, record):
            calls.append((system, record))
            return self.snapshot
        candidate = stage_exact_source(self.grant,
                  current_authenticated_owner="host-user",
                  grant_verifier=lambda _: True, read_current=reader)
        self.assertEqual(len(calls), 2)
        self.assertEqual(candidate.content_sha256, self.grant.expected_sha256)
        self.assertEqual(self.ledger.db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0], 0)

    def test_wrong_authenticated_owner_cannot_claim_same_grant(self):
        with self.assertRaisesRegex(PermissionError, "AUTHENTICATED_OWNER_MISMATCH"):
            self.verify(owner="another-user")

    def test_unapproved_or_revoked_collection_consent_is_denied(self):
        with self.assertRaisesRegex(PermissionError, "COLLECTION_CONSENT_UNAVAILABLE"):
            self.verify(verifier=lambda _: False)
        with self.assertRaisesRegex(PermissionError, "CURRENT_GRANT_UNAVAILABLE"):
            self.verify(verifier=lambda _: 1/0)
        with self.assertRaisesRegex(PermissionError, "CURRENT_GRANT_VERIFIER_REQUIRED"):
            self.verify(verifier=None)

    def test_claimed_user_role_without_host_verification_rejected(self):
        for fields in (
            dict(actor_verified=False),
            dict(actor_verified="true"),
            dict(actor_kind="assistant"),
            dict(actor_kind="quoted-owner"),
            dict(actor_principal_id="other-owner"),
            dict(complete=False),
            dict(complete=1),
        ):
            with self.subTest(fields=fields):
                with self.assertRaisesRegex(PermissionError, "UNVERIFIED_OWNER_SOURCE"):
                    self.verify(snapshot=replace(self.snapshot, **fields))

    def test_unknown_or_changed_source_revision_refused(self):
        with self.assertRaisesRegex(PermissionError, "SOURCE_REVISION_MISMATCH"):
            self.verify(snapshot=replace(self.snapshot, source_revision="rev-2"))
        with self.assertRaisesRegex(PermissionError, "SOURCE_REVISION_MISMATCH"):
            self.verify(snapshot=replace(self.snapshot, source_record_id="foreign-record"))
        with self.assertRaisesRegex(PermissionError, "SOURCE_REVISION_MISMATCH"):
            self.verify(snapshot=replace(self.snapshot, source_uri="chat:other"))

    def test_changed_text_even_if_source_revision_same_is_rejected(self):
        with self.assertRaisesRegex(PermissionError, "SOURCE_CONTENT_CHANGED"):
            self.verify(snapshot=replace(self.snapshot, content="DIFFERENT"))

    def test_missing_or_malformed_consent_and_grants_rejected(self):
        for fields in (
            dict(scope="*"), dict(privacy="unknown"), dict(consent_id=""),
            dict(source_system="unknown"), dict(source_record_id="../outside"),
            dict(expected_sha256="bad"),
        ):
            with self.subTest(fields=fields):
                with self.assertRaisesRegex(ValueError, "INVALID_SOURCE_GRANT"):
                    self.verify(grant=replace(self.grant, **fields))

    def test_oversized_or_empty_source_rejected(self):
        with self.assertRaisesRegex(ValueError, "SOURCE_BYTES_INVALID"):
            self.verify(snapshot=replace(self.snapshot, content="A"*32769))
        with self.assertRaisesRegex(ValueError, "SOURCE_BYTES_INVALID"):
            self.verify(snapshot=replace(self.snapshot, content=" "))

    def test_invalid_event_time_is_not_inferred(self):
        for value in ("2026-11-10", "tomorrow", "2026-14-99T11:00:00Z"):
            with self.subTest(time=value):
                with self.assertRaisesRegex(ValueError, "UNVERIFIED_SOURCE_EVENT_TIME"):
                    self.verify(snapshot=replace(self.snapshot, observed_at=value))
        self.assertIsNone(self.verify(snapshot=replace(self.snapshot, observed_at=None)).observed_at)

    def test_source_change_between_two_reads_fails_closed(self):
        calls = []
        def reader(*_):
            calls.append(1)
            if len(calls) == 1:
                return self.snapshot
            return replace(self.snapshot, observed_at="2026-11-10T12:35:00+09:00")
        with self.assertRaisesRegex(RuntimeError, "SOURCE_CHANGED_DURING_ADMISSION"):
            stage_exact_source(self.grant,
                current_authenticated_owner="host-user",
                grant_verifier=lambda _: True, read_current=reader)

    def test_consent_revoked_during_staging_blocks(self):
        permitted = []
        def check(_):
            permitted.append(1)
            return len(permitted) == 1
        with self.assertRaisesRegex(PermissionError, "COLLECTION_CONSENT_UNAVAILABLE"):
            stage_exact_source(self.grant,
                current_authenticated_owner="host-user",
                grant_verifier=check, read_current=lambda *_: self.snapshot)

    def test_source_reader_failure_has_only_fixed_reason(self):
        def broken(*_):
            raise RuntimeError("PRIVATE-SYNTHETIC-USER-UTTERANCE")
        with self.assertRaisesRegex(RuntimeError, "^SOURCE_RECONCILE_REQUIRED$"):
            stage_exact_source(self.grant,
                current_authenticated_owner="host-user",
                grant_verifier=lambda _: True, read_current=broken)


if __name__ == "__main__":
    unittest.main()
