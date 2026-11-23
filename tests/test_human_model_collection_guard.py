"""Synthetic contract: Guard's exact Operator approval is required for collection."""
import hashlib
import sqlite3
import sys
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ai_foundation.core import CanonContract, Decision, GuardState, TaskPlan
from ai_foundation.guard import GuardCore
from ai_foundation.human_model_collection_guard import GuardCollectionConsent, collection_intent
from ai_foundation.human_model_context import HumanModelBinding
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.store import SQLiteGuardStore, approval_request_ref

sys.path.insert(0, str(Path(__file__).parents[1] / "experiments" / "human_model"))
from human_model_ledger import Ledger
from human_model_source_admission import HostCollectionGrant, TrustedSourceSnapshot
from human_model_owner_publication import prepare_admission_schema, publish_exact_owner_observation, reconcile_cancelled_collection_consent
import storage_location
from foundation_readonly import read_view_snapshot

TEXT = "PRIVATE-SYNTHETIC-SOURCE-ONLY"


def environment(tmp_path):
    store = SQLiteGuardStore(tmp_path / "guard.db")
    guard = GuardCore(GuardState(), store=store)
    binding = HumanModelBinding(
        owner_id="host-owner", root=str(tmp_path / "HumanModel"),
        view_id="approved-view", scopes=("work",), max_privacy="private")
    canon = CanonContract("host-canonical-policy", "current-canon")
    grant = SimpleNamespace(
        owner_id="host-owner", source_system="chat",
        source_record_id="message-1", source_revision="rev-1",
        source_uri="synthetic:chat:message-1", scope="work",
        privacy="private", purpose="owner-direct-source",
        consent_id="owner-collection-1", consent_revision="v1",
        expected_sha256=hashlib.sha256(TEXT.encode()).hexdigest())
    verifier = GuardCollectionConsent(authenticated_owner="host-owner",
                                      binding=binding, guard=guard, canon=canon)
    return store, guard, binding, canon, grant, verifier


def approve_existing_operator(store, guard, intent):
    assert store.request_approval(
        intent.run_id, intent.action, intent.target,
        intent.canon_revision, intent.effect_id)
    with sqlite3.connect(store.path) as db:
        row = db.execute(
            "SELECT action,target,request_nonce,canon_revision,effect_id "
            "FROM approval_requests WHERE run_id=?", (intent.run_id,)).fetchone()
    ref = approval_request_ref(intent.run_id, *row)
    result = OperatorActions(guard).approve_pending(intent.run_id, ref)
    assert result.ok and result.status == "APPROVED"


def test_preflight_is_not_collection_consent(tmp_path):
    store, guard, binding, canon, grant, verifier = environment(tmp_path)
    intent = collection_intent(grant, binding=binding, canon=canon)
    plan = TaskPlan(intent.run_id, intent.action, intent.target,
                    canon_revision=intent.canon_revision, effect_id=intent.effect_id)
    assert guard.preflight(plan, canon) is Decision.ALLOW
    assert verifier(grant) is False


def test_exact_existing_operator_approval_allows_host_collection(tmp_path):
    store, guard, binding, canon, grant, verifier = environment(tmp_path)
    intent = collection_intent(grant, binding=binding, canon=canon)
    assert intent.target.startswith("human-model:collect:")
    assert TEXT not in intent.target and grant.source_uri not in intent.target
    approve_existing_operator(store, guard, intent)
    assert verifier(grant) is True
    assert verifier(grant) is True
    assert guard.state.spent == 0


def test_changed_source_purpose_consent_revision_or_owner_denied(tmp_path):
    store, guard, binding, canon, grant, verifier = environment(tmp_path)
    approve_existing_operator(store, guard, collection_intent(
        grant, binding=binding, canon=canon))
    for field, value in (
        ("source_revision", "rev-2"), ("source_uri", "synthetic:another"),
        ("source_record_id", "message-2"), ("expected_sha256", "0"*64),
        ("purpose", "broader-purpose"), ("consent_revision", "v2"),
        ("scope", "personal"), ("owner_id", "foreign"),
    ):
        assert verifier(SimpleNamespace(**{**vars(grant), field: value})) is False


def test_cancelled_or_changed_canon_denies(tmp_path):
    store, guard, binding, canon, grant, verifier = environment(tmp_path)
    approve_existing_operator(store, guard, collection_intent(
        grant, binding=binding, canon=canon))
    assert verifier(grant)
    guard.cancel(grant.consent_id)
    assert not verifier(grant)
    another = GuardCore(GuardState(), store=store)
    assert not GuardCollectionConsent(authenticated_owner="host-owner",
        binding=binding, guard=another,
        canon=CanonContract("host", "changed-canon"))(grant)
    assert not GuardCollectionConsent(authenticated_owner="host-owner",
        binding=binding, guard=another,
        canon=CanonContract("host", "current-canon", clear=False))(grant)


def test_foreign_or_shareable_host_refused(tmp_path):
    store, guard, binding, canon, grant, _ = environment(tmp_path)
    with pytest.raises(PermissionError):
        GuardCollectionConsent(authenticated_owner="foreign",
            binding=binding, guard=guard, canon=canon)
    with pytest.raises(PermissionError):
        GuardCollectionConsent(authenticated_owner="host-owner",
            binding=replace(binding, max_privacy="shareable"),
            guard=guard, canon=canon)
    assert not GuardCollectionConsent(authenticated_owner="host-owner",
        binding=binding, guard=GuardCore(GuardState()), canon=canon)(grant)


def test_legacy_unbound_approval_is_not_collection_consent(tmp_path):
    store, guard, binding, canon, grant, verifier = environment(tmp_path)
    guard.approve(grant.consent_id)
    assert verifier(grant) is False


def test_intent_is_stable_and_contains_no_personal_text(tmp_path):
    store, guard, binding, canon, grant, verifier = environment(tmp_path)
    a = collection_intent(grant, binding=binding, canon=canon)
    assert a == collection_intent(grant, binding=binding, canon=canon)
    assert a.action == "human_model_collect"
    assert TEXT not in repr(a) and grant.source_uri not in repr(a)


def test_exact_existing_guard_operator_consent_drives_owner_writer(tmp_path):
    store, guard, binding, canon, sample, verifier = environment(tmp_path)
    grant = HostCollectionGrant(**vars(sample))
    snapshot = TrustedSourceSnapshot(
        source_system="chat", source_record_id="message-1",
        source_revision="rev-1", source_uri=sample.source_uri,
        actor_principal_id="host-owner", actor_kind="owner",
        actor_verified=True, complete=True, content=TEXT,
        observed_at="2026-11-10T12:00:00+09:00",
    )
    ledger = Ledger(tmp_path / "human_model.sqlite3")
    try:
        prepare_admission_schema(ledger)
        with pytest.raises(PermissionError, match="COLLECTION_CONSENT_UNAVAILABLE"):
            publish_exact_owner_observation(
                ledger, grant, current_authenticated_owner="host-owner",
                grant_verifier=verifier, read_current=lambda *_: snapshot)
        assert ledger.db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0
        approve_existing_operator(store, guard, collection_intent(
            grant, binding=binding, canon=canon))
        written = publish_exact_owner_observation(
            ledger, grant, current_authenticated_owner="host-owner",
            grant_verifier=verifier, read_current=lambda *_: snapshot)
        assert written.created is True
        assert ledger.db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
        assert ledger.db.execute("SELECT COUNT(*) FROM human_source_admissions").fetchone()[0] == 1
        # A later Guard cancellation prevents replay from being presented
        # as a new current collection authorization.
        ledger.define_view(view_id="work", purpose="synthetic host",
                           audience="foundation", allowed_scopes=["work"],
                           max_privacy="private")
        ledger.rebuild_view(view_id="work")
        guard.cancel(grant.consent_id)
        receipt = reconcile_cancelled_collection_consent(
            ledger, grant.consent_id, current_authenticated_owner="host-owner",
            is_guard_cancelled=store.is_cancelled)
        assert receipt.withdrawn_count == 1
        assert ledger.db.execute("SELECT stale FROM model_views").fetchone() == (1,)
        ledger.rebuild_view(view_id="work")
        assert ledger.query(view_id="work",scope="work",audience="foundation") == []
        assert reconcile_cancelled_collection_consent(
            ledger, grant.consent_id, current_authenticated_owner="host-owner",
            is_guard_cancelled=store.is_cancelled).withdrawn_count == 0
        with pytest.raises(PermissionError, match="COLLECTION_CONSENT_UNAVAILABLE"):
            publish_exact_owner_observation(
                ledger, grant, current_authenticated_owner="host-owner",
                grant_verifier=verifier, read_current=lambda *_: snapshot)
    finally:
        ledger.close()



def test_reader_blocks_revoked_or_missing_grant_before_view_rebuild(tmp_path, monkeypatch):
    store, guard, binding, canon, sample, verifier = environment(tmp_path)
    grant = HostCollectionGrant(**vars(sample))
    snap = TrustedSourceSnapshot(
        source_system=grant.source_system,
        source_record_id=grant.source_record_id,
        source_revision=grant.source_revision, source_uri=grant.source_uri,
        actor_principal_id="host-owner", actor_kind="owner",
        actor_verified=True, complete=True, content=TEXT,
        observed_at="2026-11-10T13:00:00+09:00",
    )
    ledger_path = tmp_path / "HumanModel" / "ledger" / "human_model.sqlite3"
    ledger_path.parent.mkdir(parents=True)
    ledger = Ledger(ledger_path)
    monkeypatch.setattr(storage_location, "validated_ledger_path",
                        lambda *args, **kwargs: ledger_path)
    try:
        prepare_admission_schema(ledger)
        approve_existing_operator(
            store, guard, collection_intent(grant,binding=binding,canon=canon))
        publish_exact_owner_observation(
            ledger,grant,current_authenticated_owner="host-owner",
            grant_verifier=verifier,read_current=lambda *_: snap)
        ledger.define_view(view_id="work",purpose="synthetic",
                           audience="foundation",allowed_scopes=["work"],
                           max_privacy="private")
        ledger.rebuild_view(view_id="work")
        opts = dict(view_id="work",scope="work",max_privacy="private")
        # New owner evidence cannot be served by a legacy unbound reader.
        with pytest.raises(PermissionError, match="current owner collection grant"):
            read_view_snapshot(binding.root, **opts)
        active = read_view_snapshot(binding.root, **opts,
                                    collection_current=verifier.active_digest)
        assert len(active["records"]) == 1 and active["records"][0]["content"] == TEXT
        calls = []
        def changing_consent(digest):
            calls.append(digest)
            return len(calls) == 1
        with pytest.raises(PermissionError, match="collection grant changed during read"):
            read_view_snapshot(binding.root, **opts,
                               collection_current=changing_consent)
        assert len(calls) == 2
        assert verifier.active_digest(hashlib.sha256(grant.consent_id.encode()).hexdigest())
        guard.cancel(grant.consent_id)
        # Cancellation revokes read access even BEFORE asynchronous
        # invalidation/rebuild of the persisted source View.
        with pytest.raises(PermissionError, match="collection grant revoked"):
            read_view_snapshot(binding.root, **opts,
                               collection_current=verifier.active_digest)
        reconcile_cancelled_collection_consent(
            ledger, grant.consent_id, current_authenticated_owner="host-owner",
            is_guard_cancelled=store.is_cancelled)
        ledger.rebuild_view(view_id="work")
        clean = read_view_snapshot(binding.root, **opts,
                                   collection_current=verifier.active_digest)
        assert clean["records"] == []
    finally:
        ledger.close()
