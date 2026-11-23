"""Host-owned, no-model admission of an exact first-person source record.

This module is a staging boundary, NOT an API endpoint or an authentication
system. The host MUST independently authenticate the owner, verify a current,
purpose-bound collection grant using its existing Guard/consent authority, and
supply a trusted source adapter. Source text, model output and remote requests
cannot issue grants or attest actor identity. No ledger write occurs here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import re

from human_model_ledger import PRIVACY

_RECORD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_SOURCE = frozenset({"chat", "drive", "explicit-owner-input", "owner-event"})


def _nonempty(value, *, limit=256):
    return type(value) is str and bool(value.strip()) and len(value) <= limit


@dataclass(frozen=True)
class HostCollectionGrant:
    """Host-produced claim that STILL requires current host verification.

    The owner comes from the server authentication boundary, never a field
    copied from an agent/tool call or from source text. Consent here only
    covers collection, not profile endorsement, disclosure or effect approval.
    """
    owner_id: str
    source_system: str
    source_record_id: str
    source_revision: str
    source_uri: str
    scope: str
    privacy: str
    purpose: str
    consent_id: str
    consent_revision: str
    expected_sha256: str


@dataclass(frozen=True)
class TrustedSourceSnapshot:
    """Source adapter's actual read, not a model-generated claim.

    actor_verified must be grounded in trusted source authentication metadata,
    never source prose or an unchecked actor=user field.
    """
    source_system: str
    source_record_id: str
    source_revision: str
    source_uri: str
    actor_principal_id: str
    actor_kind: str
    actor_verified: bool
    complete: bool
    content: str
    observed_at: str | None = None


@dataclass(frozen=True)
class AdmittedEvidence:
    """Private candidate. Never serialize as a public CI/Operator receipt."""
    source_uri: str
    source_revision: str
    scope: str
    privacy: str
    content: str
    observed_at: str | None
    content_sha256: str
    owner_id: str
    consent_id: str
    consent_revision: str
    purpose: str

    def safe_receipt(self):
        return {
            "status": "ADMITTED_SOURCE_ONLY",
            "kind": "observation",
            "execution_authority": False,
            "person_fact_approved": False,
            "source_authentication": "HOST_REQUIRED",
        }


def verify_source_admission(
    grant: HostCollectionGrant,
    snapshot: TrustedSourceSnapshot,
    *,
    current_authenticated_owner: str,
    grant_verifier,
    max_bytes: int = 32768,
) -> AdmittedEvidence:
    """Model-free, bounded, fail-closed staging; source stays in host memory.

    grant_verifier MUST verify the owner's exact, fresh, unrevoked collection
    permission and the existing Guard policy, not merely parse this dataclass.
    """
    if type(grant) is not HostCollectionGrant or type(snapshot) is not TrustedSourceSnapshot:
        raise PermissionError("HOST_BOUND_SOURCE_REQUIRED")
    if not _nonempty(current_authenticated_owner) or grant.owner_id != current_authenticated_owner:
        raise PermissionError("AUTHENTICATED_OWNER_MISMATCH")
    if (grant.source_system not in _SOURCE
            or any(not _nonempty(getattr(grant, attr)) for attr in (
                "source_record_id", "source_revision", "scope", "purpose",
                "consent_id", "consent_revision"))
            or not _nonempty(grant.source_uri, limit=512)
            or grant.scope == "*" or grant.privacy != "private"
            or type(grant.expected_sha256) is not str
            or not _SHA.fullmatch(grant.expected_sha256)
            or not _RECORD.fullmatch(grant.source_record_id)):
        raise ValueError("INVALID_SOURCE_GRANT")
    if (type(max_bytes) is not int or not 1 <= max_bytes <= 32768):
        raise ValueError("INTAKE_BYTES_LIMIT_INVALID")
    if not callable(grant_verifier):
        raise PermissionError("CURRENT_GRANT_VERIFIER_REQUIRED")
    try:
        authorized = grant_verifier(grant)
    except Exception:
        raise PermissionError("CURRENT_GRANT_UNAVAILABLE") from None
    if authorized is not True:
        raise PermissionError("COLLECTION_CONSENT_UNAVAILABLE")
    if (snapshot.source_system != grant.source_system
            or snapshot.source_record_id != grant.source_record_id
            or snapshot.source_revision != grant.source_revision
            or snapshot.source_uri != grant.source_uri):
        raise PermissionError("SOURCE_REVISION_MISMATCH")
    if (snapshot.actor_verified is not True or snapshot.complete is not True
            or snapshot.actor_kind != "owner"
            or snapshot.actor_principal_id != current_authenticated_owner):
        raise PermissionError("UNVERIFIED_OWNER_SOURCE")
    if (type(snapshot.content) is not str or not snapshot.content.strip()
            or len(snapshot.content.encode("utf-8")) > max_bytes):
        raise ValueError("SOURCE_BYTES_INVALID")
    calculated = hashlib.sha256(snapshot.content.encode("utf-8")).hexdigest()
    if calculated != grant.expected_sha256:
        raise PermissionError("SOURCE_CONTENT_CHANGED")
    if snapshot.observed_at is not None:
        if not _nonempty(snapshot.observed_at, limit=48):
            raise ValueError("UNVERIFIED_SOURCE_EVENT_TIME")
        try:
            parsed = datetime.fromisoformat(snapshot.observed_at.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("UNVERIFIED_SOURCE_EVENT_TIME") from None
        if parsed.tzinfo is None:
            raise ValueError("UNVERIFIED_SOURCE_EVENT_TIME")

    # An authenticated owner utterance is merely observed source evidence;
    # inferred preference, persistent personal decision and permission are
    # separate objects with their own owner review.
    return AdmittedEvidence(
        source_uri=grant.source_uri, source_revision=grant.source_revision,
        scope=grant.scope, privacy=grant.privacy, content=snapshot.content,
        observed_at=snapshot.observed_at, content_sha256=calculated,
        owner_id=grant.owner_id, consent_id=grant.consent_id,
        consent_revision=grant.consent_revision, purpose=grant.purpose,
    )


def stage_exact_source(
    grant: HostCollectionGrant,
    *,
    current_authenticated_owner: str,
    grant_verifier,
    read_current,
) -> AdmittedEvidence:
    """Read twice under host control. Never write or schedule a model.

    A fresh source-and-grant check is required again before any publication.
    """
    if not callable(read_current):
        raise PermissionError("TRUSTED_READER_REQUIRED")
    try:
        first = read_current(grant.source_system, grant.source_record_id)
        candidate = verify_source_admission(
            grant, first, current_authenticated_owner=current_authenticated_owner,
            grant_verifier=grant_verifier)
        second = read_current(grant.source_system, grant.source_record_id)
        check = verify_source_admission(
            grant, second, current_authenticated_owner=current_authenticated_owner,
            grant_verifier=grant_verifier)
    except (PermissionError, ValueError):
        raise
    except Exception:
        raise RuntimeError("SOURCE_RECONCILE_REQUIRED") from None
    if candidate != check:
        raise RuntimeError("SOURCE_CHANGED_DURING_ADMISSION")
    return candidate
