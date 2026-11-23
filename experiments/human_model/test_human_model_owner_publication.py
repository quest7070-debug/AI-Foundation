"""Synthetic-only atomic write acceptance for owner-attested evidence."""
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from human_model_ledger import Ledger
from human_model_management_audit import audit_ledger
from human_model_recovery_drill import verify_recovery_copy
from human_model_owner_publication import (
    prepare_admission_schema, publish_exact_owner_observation,
    withdraw_attested_owner_source,
    reconcile_attested_source_revision,
    reconcile_cancelled_collection_consent,
    owner_lifecycle_tick,
)
from human_model_source_admission import HostCollectionGrant, TrustedSourceSnapshot

TEXT = "SYNTHETIC-CONFIDENTIAL-OWNER-EVIDENCE"


class HumanModelOwnerPublicationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ledger = Ledger(Path(tmp.name) / "ledger.sqlite3")
        self.addCleanup(self.ledger.close)
        self.grant = HostCollectionGrant(
            owner_id="authenticated", source_system="chat",
            source_record_id="message-7", source_revision="version-1",
            source_uri="synthetic:chat:message-7", scope="career",
            privacy="private", purpose="explicit collection of an owner record",
            consent_id="host-consent-event", consent_revision="2",
            expected_sha256=hashlib.sha256(TEXT.encode()).hexdigest(),
        )
        self.snap = TrustedSourceSnapshot(
            source_system="chat", source_record_id="message-7",
            source_revision="version-1", source_uri="synthetic:chat:message-7",
            actor_principal_id="authenticated", actor_kind="owner",
            actor_verified=True, complete=True, content=TEXT,
            observed_at="2026-11-10T09:01:02+09:00",
        )
        self.ledger.define_view(
            view_id="career", purpose="synthetic", audience="foundation",
            allowed_scopes=["career"], max_privacy="private")
        self.ledger.rebuild_view(view_id="career")

    def publish(self, grant=None, source=None, verifier=None):
        return publish_exact_owner_observation(
            self.ledger, self.grant if grant is None else grant,
            current_authenticated_owner="authenticated",
            grant_verifier=verifier if verifier is not None else lambda _: True,
            read_current=lambda *_: self.snap if source is None else source,
        )

    def rows(self, table):
        return self.ledger.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_explicit_migration_is_required_before_writes(self):
        with self.assertRaisesRegex(RuntimeError, "OWNER_ADMISSION_SCHEMA_NOT_PREPARED"):
            self.publish()
        self.assertEqual(self.rows("evidence"), 0)
        names = {x[0] for x in self.ledger.db.execute("SELECT name FROM sqlite_master")}
        self.assertNotIn("human_source_admissions", names)

    def test_atomic_write_and_proof_with_same_external_ledger(self):
        prepare_admission_schema(self.ledger)
        result = self.publish()
        self.assertTrue(result.created)
        self.assertEqual(self.rows("evidence"), 1)
        self.assertEqual(self.rows("human_source_admissions"), 1)
        self.assertEqual(self.rows("change_log"), 1)
        eid = self.ledger.db.execute("SELECT id FROM evidence").fetchone()[0]
        self.assertEqual(eid, result.evidence_id)
        observed = self.ledger.db.execute(
            "SELECT kind,privacy,content_sha256 FROM evidence").fetchone()
        self.assertEqual(observed, ("observation", "private", self.grant.expected_sha256))
        proof = self.ledger.db.execute(
            "SELECT attestation,source_sha256 FROM human_source_admissions").fetchone()
        self.assertEqual(proof, ("HOST_VERIFIED_OWNER_SOURCE", self.grant.expected_sha256))
        self.assertEqual(self.ledger.db.execute(
            "SELECT stale FROM model_views WHERE id='career'").fetchone(), (1,))
        safe = result.safe_receipt()
        self.assertFalse(safe["person_fact_approved"])
        self.assertFalse(safe["execution_authority"])
        self.assertNotIn(TEXT, json.dumps(safe))
        self.assertNotIn("message-7", json.dumps(safe))
        self.assertNotIn(eid, json.dumps(safe))

    def test_duplicate_replay_is_exactly_idempotent(self):
        prepare_admission_schema(self.ledger)
        first = self.publish()
        self.ledger.rebuild_view(view_id="career")
        second = self.publish()
        self.assertFalse(second.created)
        self.assertEqual(first.evidence_id, second.evidence_id)
        self.assertEqual(self.rows("change_log"), 1)
        self.assertEqual(self.rows("human_source_admissions"), 1)
        self.assertEqual(self.ledger.db.execute(
            "SELECT stale FROM model_views WHERE id='career'").fetchone(), (0,))

    def test_legacy_unattested_evidence_cannot_gain_silent_proof(self):
        prepare_admission_schema(self.ledger)
        self.ledger.add(source_uri=self.grant.source_uri,
                        source_revision=self.grant.source_revision,
                        kind="observation", scope="career", privacy="private",
                        content=TEXT, observed_at=self.snap.observed_at)
        with self.assertRaisesRegex(PermissionError, "EXISTING_SOURCE_NOT_ATTESTED"):
            self.publish()
        self.assertEqual(self.rows("human_source_admissions"), 0)

    def test_reused_revision_with_changed_grant_rejected(self):
        prepare_admission_schema(self.ledger)
        self.publish()
        for grant in (
            replace(self.grant, purpose="different scope of consent"),
            replace(self.grant, consent_revision="3"),
        ):
            with self.assertRaisesRegex(PermissionError, "EXISTING_SOURCE_NOT_ATTESTED"):
                self.publish(grant=grant)

    def test_revision_collision_with_new_body_fails(self):
        prepare_admission_schema(self.ledger)
        self.publish()
        altered = replace(self.snap, content="DIFFERENT")
        altered_grant = replace(self.grant, expected_sha256=hashlib.sha256(
            altered.content.encode()).hexdigest())
        with self.assertRaisesRegex(ValueError, "SOURCE_REVISION_CONFLICT"):
            self.publish(grant=altered_grant, source=altered)

    def test_attempted_owner_spoof_does_not_write(self):
        prepare_admission_schema(self.ledger)
        with self.assertRaisesRegex(PermissionError, "UNVERIFIED_OWNER_SOURCE"):
            self.publish(source=replace(self.snap, actor_principal_id="different"))
        self.assertEqual(self.rows("evidence"), 0)

    def test_revoked_grant_blocks_publication(self):
        prepare_admission_schema(self.ledger)
        with self.assertRaisesRegex(PermissionError, "COLLECTION_CONSENT_UNAVAILABLE"):
            self.publish(verifier=lambda _: False)
        self.assertEqual(self.rows("evidence"), 0)

    def test_fail_in_proof_insert_rolls_back_original_and_view(self):
        prepare_admission_schema(self.ledger)
        with self.ledger.db:
            self.ledger.db.execute("""CREATE TRIGGER fail_source_proof BEFORE INSERT ON
                human_source_admissions BEGIN SELECT RAISE(ABORT, 'SECRET-SENTINEL'); END;""")
        with self.assertRaisesRegex(RuntimeError, "^SOURCE_PUBLICATION_UNAVAILABLE$"):
            self.publish()
        self.assertEqual(self.rows("evidence"), 0)
        self.assertEqual(self.rows("change_log"), 0)
        self.assertEqual(self.ledger.db.execute(
            "SELECT stale FROM model_views WHERE id='career'").fetchone(), (0,))

    def test_no_new_permission_from_publication(self):
        prepare_admission_schema(self.ledger)
        receipt = self.publish().safe_receipt()
        self.assertEqual(receipt["evidence_kind"], "observation")
        self.assertIs(receipt["person_fact_approved"], False)
        self.assertIs(receipt["execution_authority"], False)
        self.assertEqual(self.rows("evidence"), 1)


    def test_withdrawal_blocks_view_and_prevents_silent_replay(self):
        prepare_admission_schema(self.ledger)
        existing = self.publish()
        self.ledger.rebuild_view(view_id="career")
        withdrawn = withdraw_attested_owner_source(
            self.ledger, existing.evidence_id,
            current_authenticated_owner="authenticated",
            authorize_withdrawal=lambda *_: True,
        )
        self.assertTrue(withdrawn.changed)
        self.assertEqual(withdrawn.safe_receipt()["original_erasure_proven"], False)
        self.assertEqual(self.rows("evidence"), 1)
        self.assertEqual(self.ledger.db.execute(
            "SELECT stale FROM model_views WHERE id='career'").fetchone(), (1,))
        with self.assertRaises(RuntimeError):
            self.ledger.query(view_id="career", scope="career", audience="foundation")
        self.ledger.rebuild_view(view_id="career")
        self.assertEqual(self.ledger.query(
            view_id="career", scope="career", audience="foundation"), [])
        with self.assertRaisesRegex(PermissionError, "SOURCE_PREVIOUSLY_WITHDRAWN"):
            self.publish()

    def test_withdrawal_is_idempotent_no_additional_audit_event(self):
        prepare_admission_schema(self.ledger)
        eid = self.publish().evidence_id
        def withdraw():
            return withdraw_attested_owner_source(
                self.ledger, eid, current_authenticated_owner="authenticated",
                authorize_withdrawal=lambda *_: True)
        self.assertTrue(withdraw().changed)
        self.assertFalse(withdraw().changed)
        self.assertEqual(self.rows("change_log"), 2)

    def test_foreign_owner_and_denied_withdrawal_do_not_change_view(self):
        prepare_admission_schema(self.ledger)
        eid = self.publish().evidence_id
        self.ledger.rebuild_view(view_id="career")
        for owner, checker, reason in (
            ("foreign", lambda *_: True, "OWNER_SOURCE_NOT_BOUND"),
            ("authenticated", lambda *_: False, "OWNER_WITHDRAWAL_DENIED"),
        ):
            with self.subTest(owner=owner, reason=reason):
                with self.assertRaisesRegex(PermissionError, reason):
                    withdraw_attested_owner_source(
                        self.ledger, eid, current_authenticated_owner=owner,
                        authorize_withdrawal=checker,
                    )
        self.assertEqual(self.ledger.db.execute(
            "SELECT state FROM human_source_admissions").fetchone(), ("ACTIVE",))
        self.assertEqual(self.ledger.db.execute(
            "SELECT stale FROM model_views WHERE id='career'").fetchone(), (0,))

    def test_withdrawal_sqlite_failure_rolls_back_and_redacts_error(self):
        prepare_admission_schema(self.ledger)
        eid = self.publish().evidence_id
        self.ledger.rebuild_view(view_id="career")
        with self.ledger.db:
            self.ledger.db.execute("""CREATE TRIGGER deny_withdraw BEFORE UPDATE ON
                human_source_admissions BEGIN SELECT RAISE(ABORT, 'PRIVATE-TEXT'); END;""")
        with self.assertRaisesRegex(RuntimeError, "^OWNER_WITHDRAWAL_STORAGE_UNAVAILABLE$"):
            withdraw_attested_owner_source(
                self.ledger, eid, current_authenticated_owner="authenticated",
                authorize_withdrawal=lambda *_: True,
            )
        self.assertEqual(self.ledger.db.execute(
            "SELECT stale FROM model_views WHERE id='career'").fetchone(), (0,))
        self.assertEqual(self.ledger.db.execute(
            "SELECT state FROM human_source_admissions").fetchone(), ("ACTIVE",))
        self.assertEqual(self.rows("change_log"), 1)

    def test_unattested_source_cannot_be_withdrawn_as_owner_attested(self):
        prepare_admission_schema(self.ledger)
        eid = self.ledger.add(
            source_uri="synthetic:legacy", source_revision="1",
            kind="observation", scope="career", privacy="private",
            content="synthetic", observed_at=None)
        with self.assertRaisesRegex(PermissionError, "OWNER_SOURCE_NOT_BOUND"):
            withdraw_attested_owner_source(
                self.ledger, eid, current_authenticated_owner="authenticated",
                authorize_withdrawal=lambda *_: True,
            )


    def test_management_audit_detects_revoked_source_reintroduced_to_view(self):
        prepare_admission_schema(self.ledger)
        eid = self.publish().evidence_id
        withdraw_attested_owner_source(
            self.ledger, eid, current_authenticated_owner="authenticated",
            authorize_withdrawal=lambda *_: True,
        )
        self.ledger.rebuild_view(view_id="career")
        summary = audit_ledger(self.ledger.db)
        self.assertEqual(summary["admitted_sources"], 1)
        self.assertEqual(summary["withdrawn_sources"], 1)
        self.assertEqual(summary["withdrawn_in_current_view"], 0)
        self.assertEqual(summary["status"], "STRUCTURE_OK_SOURCE_UNVERIFIED")
        with self.ledger.db:
            self.ledger.db.execute(
                "INSERT INTO model_sources(model_id,evidence_id) VALUES (?,?)",
                ("career", eid),
            )
        summary = audit_ledger(self.ledger.db)
        self.assertEqual(summary["withdrawn_in_current_view"], 1)
        self.assertEqual(summary["status"], "STRUCTURE_INVALID")

    def test_management_audit_flags_proof_hash_corruption(self):
        prepare_admission_schema(self.ledger)
        self.publish()
        self.ledger.rebuild_view(view_id="career")
        with self.ledger.db:
            self.ledger.db.execute(
                "UPDATE human_source_admissions SET source_sha256=?",
                ("0" * 64,),
            )
        result = audit_ledger(self.ledger.db)
        self.assertEqual(result["status"], "STRUCTURE_INVALID")
        self.assertEqual(result["invalid_admission_links"], 1)
        self.assertNotIn(TEXT, json.dumps(result))


    def correction(self, old_id, *, suffix="2", scope="career", auth=None):
        content = "SYNTHETIC-OWNER-CORRECTION-" + suffix
        grant = replace(self.grant,
            source_uri="synthetic:chat:correction-" + suffix,
            source_record_id="message-" + suffix,
            source_revision="version-" + suffix,
            scope=scope,
            expected_sha256=hashlib.sha256(content.encode()).hexdigest())
        snap = replace(self.snap, source_uri=grant.source_uri,
                       source_record_id=grant.source_record_id,
                       source_revision=grant.source_revision,
                       content=content)
        return publish_exact_owner_observation(
            self.ledger, grant, current_authenticated_owner="authenticated",
            grant_verifier=lambda _: True,
            read_current=lambda *_: snap,
            corrects_evidence_id=old_id, authorize_correction=auth,
        )

    def test_authenticated_correction_supersedes_without_deleting_original(self):
        prepare_admission_schema(self.ledger)
        old = self.publish().evidence_id
        correction = self.correction(old, auth=lambda *_: True)
        self.assertTrue(correction.created)
        original_superseded = self.ledger.db.execute(
            "SELECT supersedes FROM evidence WHERE id=?",
            (correction.evidence_id,)).fetchone()[0]
        self.assertEqual(original_superseded, old)
        self.assertEqual(self.rows("evidence"), 2)
        self.ledger.rebuild_view(view_id="career")
        current = self.ledger.query(
            view_id="career", scope="career", audience="foundation")
        self.assertEqual([r["id"] for r in current], [correction.evidence_id])
        self.assertEqual(audit_ledger(self.ledger.db)["superseded_in_current_view"], 0)

    def test_correction_requires_separate_host_permission(self):
        prepare_admission_schema(self.ledger)
        old = self.publish().evidence_id
        with self.assertRaisesRegex(PermissionError, "EXACT_OWNER_CORRECTION_AUTHORITY_REQUIRED"):
            self.correction(old)
        with self.assertRaisesRegex(PermissionError, "OWNER_CORRECTION_DENIED"):
            self.correction(old, auth=lambda *_: False)
        self.assertEqual(self.rows("evidence"), 1)

    def test_correction_rejects_other_scope_and_withdrawn_source(self):
        prepare_admission_schema(self.ledger)
        old = self.publish().evidence_id
        with self.assertRaisesRegex(PermissionError, "CORRECTION_SOURCE_NOT_AUTHENTICATED"):
            self.correction(old, scope="personal", auth=lambda *_: True)
        withdraw_attested_owner_source(
            self.ledger, old, current_authenticated_owner="authenticated",
            authorize_withdrawal=lambda *_: True,
        )
        with self.assertRaisesRegex(PermissionError, "CORRECTION_SOURCE_NOT_AUTHENTICATED"):
            self.correction(old, auth=lambda *_: True)
        self.assertEqual(self.rows("evidence"), 1)

    def test_correction_exact_replay_only_and_second_successor_rejected(self):
        prepare_admission_schema(self.ledger)
        old = self.publish().evidence_id
        first = self.correction(old, auth=lambda *_: True)
        again = self.correction(old, auth=lambda *_: True)
        self.assertFalse(again.created)
        self.assertEqual(again.evidence_id, first.evidence_id)
        with self.assertRaisesRegex(ValueError, "CORRECTION_ALREADY_SUPERSEDED"):
            self.correction(old, suffix="3", auth=lambda *_: True)
        self.assertEqual(self.rows("evidence"), 2)


    def test_revision_audit_uses_record_id_not_canonical_uri(self):
        prepare_admission_schema(self.ledger)
        evidence_id = self.publish().evidence_id
        calls = []
        def reader(system, record_id):
            calls.append((system, record_id))
            if record_id != self.grant.source_record_id:
                raise RuntimeError("WRONG-LOOKUP-KEY")
            return self.snap
        receipt = reconcile_attested_source_revision(
            self.ledger, evidence_id,
            current_authenticated_owner="authenticated",
            read_current=reader)
        self.assertEqual(receipt.status, "SOURCE_STILL_CURRENT")
        self.assertEqual(calls, [(self.grant.source_system,
                                  self.grant.source_record_id)])

    def test_revision_audit_retains_current_source_without_mutation(self):
        prepare_admission_schema(self.ledger)
        eid = self.publish().evidence_id
        self.ledger.rebuild_view(view_id="career")
        read = reconcile_attested_source_revision(
            self.ledger, eid,
            current_authenticated_owner="authenticated",
            read_current=lambda *_: self.snap,
        )
        self.assertEqual(read.status, "SOURCE_STILL_CURRENT")
        self.assertEqual(self.ledger.db.execute(
            "SELECT stale FROM model_views WHERE id='career'").fetchone(), (0,))
        self.assertEqual(self.rows("change_log"), 1)

    def test_changed_source_revision_excludes_old_approved_view(self):
        prepare_admission_schema(self.ledger)
        eid = self.publish().evidence_id
        self.ledger.rebuild_view(view_id="career")
        changed = replace(self.snap, source_revision="version-2",
                          content="EDITED-OWNER-SYNTHETIC")
        receipt = reconcile_attested_source_revision(
            self.ledger, eid,
            current_authenticated_owner="authenticated",
            read_current=lambda *_: changed,
        )
        self.assertEqual(receipt.status, "SOURCE_STALE")
        self.assertEqual(self.ledger.db.execute(
            "SELECT state FROM human_source_admissions").fetchone(), ("STALE",))
        self.assertEqual(self.ledger.db.execute(
            "SELECT stale FROM model_views WHERE id='career'").fetchone(), (1,))
        self.ledger.rebuild_view(view_id="career")
        self.assertEqual(self.ledger.query(
            view_id="career", scope="career", audience="foundation"), [])
        with self.assertRaisesRegex(PermissionError, "SOURCE_REVISION_STALE"):
            self.publish()
        audit = audit_ledger(self.ledger.db)
        self.assertEqual(audit["source_stale_count"], 1)
        self.assertEqual(audit["inactive_in_current_view"], 0)

    def test_unavailable_original_fails_closed_as_stale_without_9b(self):
        prepare_admission_schema(self.ledger)
        eid = self.publish().evidence_id
        self.ledger.rebuild_view(view_id="career")
        def unavailable(*_):
            raise RuntimeError("SYNTHETIC_PRIVATE_RAW")
        result = reconcile_attested_source_revision(
            self.ledger, eid,
            current_authenticated_owner="authenticated",
            read_current=unavailable,
        )
        self.assertEqual(result.status, "SOURCE_STALE")
        self.assertEqual(result.safe_receipt()["execution_authority"], False)
        self.assertNotIn("SYNTHETIC_PRIVATE_RAW", str(result.safe_receipt()))
        self.ledger.rebuild_view(view_id="career")
        self.assertEqual(self.ledger.query(
            view_id="career", scope="career", audience="foundation"), [])

    def test_stale_source_can_be_explicitly_withdrawn_but_not_revived(self):
        prepare_admission_schema(self.ledger)
        eid = self.publish().evidence_id
        reconcile_attested_source_revision(
            self.ledger, eid,
            current_authenticated_owner="authenticated",
            read_current=lambda *_: replace(self.snap, complete=False),
        )
        result = withdraw_attested_owner_source(
            self.ledger, eid,
            current_authenticated_owner="authenticated",
            authorize_withdrawal=lambda *_: True,
        )
        self.assertTrue(result.changed)
        self.assertEqual(self.ledger.db.execute(
            "SELECT state FROM human_source_admissions").fetchone(), ("WITHDRAWN",))

    def test_foreign_source_reconciliation_is_not_an_owner_read(self):
        prepare_admission_schema(self.ledger)
        eid = self.publish().evidence_id
        with self.assertRaisesRegex(PermissionError, "OWNER_SOURCE_NOT_BOUND"):
            reconcile_attested_source_revision(
                self.ledger, eid, current_authenticated_owner="different",
                read_current=lambda *_: self.snap,
            )
        self.assertEqual(self.ledger.db.execute(
            "SELECT state FROM human_source_admissions").fetchone(), ("ACTIVE",))


    def test_guard_cancellation_requires_external_current_proof(self):
        prepare_admission_schema(self.ledger)
        self.publish()
        self.ledger.rebuild_view(view_id="career")
        with self.assertRaisesRegex(PermissionError, "GUARD_CANCEL_NOT_PROVEN"):
            reconcile_cancelled_collection_consent(
                self.ledger, self.grant.consent_id,
                current_authenticated_owner="authenticated",
                is_guard_cancelled=lambda _: False,
            )
        with self.assertRaisesRegex(PermissionError, "GUARD_CANCEL_UNAVAILABLE"):
            reconcile_cancelled_collection_consent(
                self.ledger, self.grant.consent_id,
                current_authenticated_owner="authenticated",
                is_guard_cancelled=lambda _: 1/0,
            )
        self.assertEqual(self.ledger.db.execute(
            "SELECT state FROM human_source_admissions").fetchone(), ("ACTIVE",))
        self.assertEqual(self.ledger.db.execute(
            "SELECT stale FROM model_views WHERE id='career'").fetchone(), (0,))

    def test_cancelled_collection_stops_serve_without_erasure(self):
        prepare_admission_schema(self.ledger)
        self.publish()
        self.ledger.rebuild_view(view_id="career")
        result = reconcile_cancelled_collection_consent(
            self.ledger, self.grant.consent_id,
            current_authenticated_owner="authenticated",
            is_guard_cancelled=lambda _: True,
        )
        self.assertEqual(result.withdrawn_count, 1)
        self.assertFalse(result.safe_receipt()["original_erasure_proven"])
        self.assertEqual(self.ledger.db.execute(
            "SELECT stale FROM model_views WHERE id='career'").fetchone(), (1,))
        self.ledger.rebuild_view(view_id="career")
        self.assertEqual(self.ledger.query(
            view_id="career", scope="career", audience="foundation"), [])
        self.assertEqual(self.rows("evidence"), 1)
        self.assertEqual(reconcile_cancelled_collection_consent(
            self.ledger, self.grant.consent_id,
            current_authenticated_owner="authenticated",
            is_guard_cancelled=lambda _: True,
        ).withdrawn_count, 0)
        self.assertEqual(self.rows("change_log"), 2)

    def test_foreign_owner_cannot_bulk_revoke_other_owner_evidence(self):
        prepare_admission_schema(self.ledger)
        self.publish()
        self.ledger.rebuild_view(view_id="career")
        result = reconcile_cancelled_collection_consent(
            self.ledger, self.grant.consent_id,
            current_authenticated_owner="foreign",
            is_guard_cancelled=lambda _: True,
        )
        self.assertEqual(result.withdrawn_count, 0)
        self.assertEqual(self.ledger.db.execute(
            "SELECT state FROM human_source_admissions").fetchone(), ("ACTIVE",))


    def test_owner_tick_no_model_rechecks_current_source_without_changes(self):
        prepare_admission_schema(self.ledger)
        self.publish()
        self.ledger.rebuild_view(view_id="career")
        first = owner_lifecycle_tick(
            self.ledger, current_authenticated_owner="authenticated",
            consent_current=lambda _: True, read_current=lambda *_: self.snap)
        second = owner_lifecycle_tick(
            self.ledger, current_authenticated_owner="authenticated",
            consent_current=lambda _: True, read_current=lambda *_: self.snap)
        self.assertEqual(first["status"], "OWNER_LIFECYCLE_VERIFIED")
        self.assertEqual(first["source_current"], 1)
        self.assertEqual(second["source_current"], 1)
        self.assertEqual(self.rows("change_log"), 1)
        self.assertEqual(self.ledger.db.execute(
            "SELECT stale FROM model_views WHERE id='career'").fetchone(), (0,))

    def test_owner_tick_unknown_consent_stops_serving_without_purging_original(self):
        prepare_admission_schema(self.ledger)
        self.publish()
        self.ledger.rebuild_view(view_id="career")
        result = owner_lifecycle_tick(
            self.ledger, current_authenticated_owner="authenticated",
            consent_current=lambda _: False, read_current=lambda *_: self.snap)
        self.assertEqual(result["status"], "OWNER_LIFECYCLE_REVIEW_REQUIRED")
        self.assertEqual(result["consent_unavailable"], 1)
        self.assertEqual(self.ledger.db.execute(
            "SELECT state FROM human_source_admissions").fetchone(), ("STALE",))
        self.assertEqual(self.rows("evidence"), 1)
        self.ledger.rebuild_view(view_id="career")
        self.assertEqual(self.ledger.query(
            view_id="career", scope="career", audience="foundation"), [])
        again = owner_lifecycle_tick(
            self.ledger, current_authenticated_owner="authenticated",
            consent_current=lambda _: False, read_current=lambda *_: self.snap)
        self.assertEqual(again["examined"], 0)
        self.assertEqual(self.rows("change_log"), 2)

    def test_owner_tick_source_edit_and_incomplete_batch_fail_closed(self):
        prepare_admission_schema(self.ledger)
        self.publish()
        before = owner_lifecycle_tick(
            self.ledger, current_authenticated_owner="authenticated",
            consent_current=lambda _: True, read_current=lambda *_: self.snap,
            max_records=1)
        self.assertEqual(before["source_current"], 1)
        changed = owner_lifecycle_tick(
            self.ledger, current_authenticated_owner="authenticated",
            consent_current=lambda _: True,
            read_current=lambda *_: replace(self.snap, source_revision="v2"))
        self.assertEqual(changed["source_stale"], 1)
        self.assertEqual(changed["status"], "OWNER_LIFECYCLE_REVIEW_REQUIRED")

    def test_owner_tick_cannot_scan_foreign_owner_or_without_trusted_ports(self):
        prepare_admission_schema(self.ledger)
        self.publish()
        result = owner_lifecycle_tick(
            self.ledger, current_authenticated_owner="foreign",
            consent_current=lambda _: True, read_current=lambda *_: self.snap)
        self.assertEqual(result["examined"], 0)
        with self.assertRaisesRegex(PermissionError, "OWNER_LIFECYCLE_HOST_BINDING_REQUIRED"):
            owner_lifecycle_tick(self.ledger,
                current_authenticated_owner="authenticated",
                consent_current=None, read_current=lambda *_: self.snap)


    def test_memory_recovery_copy_preserves_withdrawals_and_originals(self):
        prepare_admission_schema(self.ledger)
        first = self.publish()
        self.ledger.rebuild_view(view_id="career")
        withdraw_attested_owner_source(
            self.ledger, first.evidence_id,
            current_authenticated_owner="authenticated",
            authorize_withdrawal=lambda *_: True,
        )
        self.ledger.rebuild_view(view_id="career")
        readback = verify_recovery_copy(self.ledger.db)
        self.assertEqual(readback["status"], "RESTORE_STRUCTURE_VERIFIED")
        self.assertEqual(readback["record_count"], 1)
        self.assertEqual(readback["withdrawn_count"], 1)
        self.assertFalse(readback["durable_backup_created"])
        self.assertFalse(readback["physical_erasure_proven"])
        self.assertNotIn(TEXT, json.dumps(readback))

    def test_memory_recovery_copy_rejects_corrupt_original_without_clone_pass(self):
        prepare_admission_schema(self.ledger)
        self.publish()
        with self.ledger.db:
            self.ledger.db.execute("UPDATE evidence SET content='CORRUPTED'")
        outcome = verify_recovery_copy(self.ledger.db)
        self.assertEqual(outcome["status"], "RESTORE_DRILL_SOURCE_INVALID")


    def test_proof_record_key_corruption_invalidates_management_audit(self):
        prepare_admission_schema(self.ledger)
        self.publish()
        self.ledger.rebuild_view(view_id="career")
        with self.ledger.db:
            self.ledger.db.execute(
                "UPDATE human_source_admissions SET source_record_id=?",
                ("forged-record-id",))
        audit = audit_ledger(self.ledger.db)
        self.assertEqual(audit["status"], "STRUCTURE_INVALID")
        self.assertEqual(audit["invalid_admission_links"], 1)
        self.assertNotIn("forged-record-id", json.dumps(audit))



if __name__ == "__main__":
    unittest.main()
