"""Source-reviewed candidate IDs alone never grant runtime admission."""
from ai_foundation.development_candidate_registry import (
    SOURCE_REVIEWED, reviewed_offline_catalogue,
)
from ai_foundation.development_offline_cost import (
    OfflineObservation, cost_from_pinned_offline_source,
)


def test_exact_pinned_source_review_not_runtime_authority():
    assert set(SOURCE_REVIEWED) == {"ripgrep-14.1.1"}
    candidate = reviewed_offline_catalogue()["ripgrep-14.1.1"]
    assert candidate.repository == "https://github.com/BurntSushi/ripgrep"
    assert candidate.pinned_commit == "4649aa9700619f94cf9c66876e9549d83420e16c"
    assert candidate.license_spdx == "MIT"
    assert candidate.license_sha256 == (
        "0f96a83840e146e43c0ec96a22ec1f392e0680e6c1226e6f3ba87e0740af850f"
    )
    assert candidate.account_required is False
    assert candidate.network_runtime_required is False
    assert candidate.paid_dependencies is False
    assert cost_from_pinned_offline_source(
        "ripgrep-14.1.1", catalogue=reviewed_offline_catalogue(),
        observed=None,
    ) is None


def test_unknown_or_unverified_source_cannot_create_cost_receipt():
    import time
    catalogue = reviewed_offline_catalogue()
    candidate = catalogue["ripgrep-14.1.1"]
    claimed = OfflineObservation(
        checked_at=time.time(), observed_commit=candidate.pinned_commit,
        license_bytes=b"UNTRUSTED FAKE MIT CLAIM" * 4,
        account_required=False, network_runtime_required=False,
        paid_dependencies=False, sandbox_network_denied=True,
        source_readback_verified=True,
    )
    assert cost_from_pinned_offline_source(
        "ripgrep-14.1.1", catalogue=catalogue, observed=claimed,
    ) is None
    assert cost_from_pinned_offline_source(
        "unreviewed", catalogue=catalogue, observed=claimed,
    ) is None
    # A caller's altered local dictionary must not mutate the reviewed source.
    catalogue.clear()
    assert set(reviewed_offline_catalogue()) == {"ripgrep-14.1.1"}
