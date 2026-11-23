"""Finite source-reviewed local OSS candidate catalogue.

This is *only* a host-owned source identity list, not evidence that a tool
works, is installed, improves the product, or is approved. A candidate cannot
cause Drive writes, Issue publication, or model execution from this module.
Adding a candidate requires a reviewed source change; untrusted Drive/model
text may supply an ID but cannot edit this registry.
"""
from __future__ import annotations

from types import MappingProxyType

from .development_offline_cost import AuditedOfflinePackage

# Source commit and MIT license content are independently retrieved from the
# exact upstream tag; M1 source-only readback: GitHub Actions #42601132018.
# The executable was NOT present on that M1 host; no benchmark was performed.
_REVIEWED_SOURCE = {
    "ripgrep-14.1.1": AuditedOfflinePackage(
        candidate_id="ripgrep-14.1.1",
        repository="https://github.com/BurntSushi/ripgrep",
        pinned_commit="4649aa9700619f94cf9c66876e9549d83420e16c",
        license_spdx="MIT",
        license_sha256="0f96a83840e146e43c0ec96a22ec1f392e0680e6c1226e6f3ba87e0740af850f",
        account_required=False,
        network_runtime_required=False,
        paid_dependencies=False,
    ),
}
SOURCE_REVIEWED = MappingProxyType(_REVIEWED_SOURCE)


def reviewed_offline_catalogue():
    """Copy source identities to trusted host; produce NO runtime receipts."""
    return dict(SOURCE_REVIEWED)
