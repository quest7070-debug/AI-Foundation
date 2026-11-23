"""Host-audited, offline-only cost proof for finite allowlisted OSS candidates.

No model-supplied SPDX string or free-tier marketing copy can create a grant.
The caller must already have an immutable owner/host-reviewed candidate
manifest, verified source checkout and isolated no-egress execution context.
This adapter verifies the actual observed license bytes against that manifest.
It does not fetch source, run an installer, spend money, or install a package.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import math
import re
import time

from .development_admission import CostReceipt

_REPO = re.compile(r"https://github\.com/[A-Za-z0-9_.-]{1,80}/[A-Za-z0-9_.-]{1,100}\Z")
_SHA40 = re.compile(r"[a-f0-9]{40}\Z")
_SHA64 = re.compile(r"[a-f0-9]{64}\Z")
_CANDIDATE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")

# Permissive, standard OSS licenses only for low-risk local trials. Other
# licenses are explicit HOLD until separately reviewed, not "paid".
PERMISSIVE = frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"})


@dataclass(frozen=True)
class AuditedOfflinePackage:
    """Immutable entry from trusted host registry, not Issue/Drive/model text."""
    candidate_id: str
    repository: str
    pinned_commit: str
    license_spdx: str
    license_sha256: str
    account_required: bool
    network_runtime_required: bool
    paid_dependencies: bool


@dataclass(frozen=True)
class OfflineObservation:
    """The trusted host independently checked source and sandbox posture."""
    checked_at: float
    observed_commit: str
    license_bytes: bytes
    account_required: bool
    network_runtime_required: bool
    paid_dependencies: bool
    sandbox_network_denied: bool
    source_readback_verified: bool


def cost_from_pinned_offline_source(candidate_id, *, catalogue, observed, now=None):
    """Return verified-local cost or None (fail closed), never an approval."""
    now = time.time() if now is None else now
    # Unknown or malformed timestamps must never become an admission receipt.
    if type(now) not in (int, float) or not math.isfinite(now):
        return None
    if (type(candidate_id) is not str or not _CANDIDATE.fullmatch(candidate_id)
            or type(catalogue) is not dict or
            type(observed) is not OfflineObservation):
        return None
    entry = catalogue.get(candidate_id)
    if (type(entry) is not AuditedOfflinePackage or
            entry.candidate_id != candidate_id or
            type(entry.repository) is not str or
            not _REPO.fullmatch(entry.repository) or
            any(segment in (".", "..") for segment in entry.repository.removeprefix("https://github.com/").split("/")) or
            type(entry.pinned_commit) is not str or
            not _SHA40.fullmatch(entry.pinned_commit) or
            type(entry.license_sha256) is not str or
            not _SHA64.fullmatch(entry.license_sha256) or
            type(entry.license_spdx) is not str or
            entry.license_spdx not in PERMISSIVE):
        return None
    if (any(type(x) is not bool for x in (
            entry.account_required, entry.network_runtime_required,
            entry.paid_dependencies, observed.account_required,
            observed.network_runtime_required, observed.paid_dependencies,
            observed.sandbox_network_denied, observed.source_readback_verified))
            or any((entry.account_required, entry.network_runtime_required,
                    entry.paid_dependencies, observed.account_required,
                    observed.network_runtime_required, observed.paid_dependencies))
            or observed.sandbox_network_denied is not True or
            observed.source_readback_verified is not True):
        return None
    if (type(observed.checked_at) not in (int, float) or
            not math.isfinite(observed.checked_at) or
            not 0 <= now - observed.checked_at <= 86400 or
            observed.observed_commit != entry.pinned_commit or
            type(observed.license_bytes) is not bytes or
            not 50 <= len(observed.license_bytes) <= 65536 or
            sha256(observed.license_bytes).hexdigest() != entry.license_sha256):
        return None
    # No payment account or network can be involved in this exact host
    # sandbox. This is NOT valid for hosted inference/free cloud plans.
    return CostReceipt(
        checked_at=observed.checked_at,
        proof=entry.repository + "/commit/" + entry.pinned_commit,
        license_free=True, initial_yen=0, recurring_yen=0,
        billing="NOT_APPLICABLE_LOCAL",
    )
