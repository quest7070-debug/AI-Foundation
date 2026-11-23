"""Read-only regression: distinguish independent Operator ledger ambiguities.

No launchctl, Owner Guard, model call or service mutation.
"""
import json
import plistlib

import pytest

from ai_foundation.release_gate import ImmutableReleaseScope
from scripts.m1_operator_release_host import (
    FixedOperatorHost, OperatorHostDenied, LABEL,
)
from scripts.m1_operator_release_cli import _safe_failure_reason


def _scope():
    return ImmutableReleaseScope(
        path="m1-operator", source_sha="b" * 64,
        previous_authority="old", previous_endpoint="old",
        candidate_authority="github-commit:" + "c" * 40,
        candidate_endpoint="new", rollback_procedure="restore",
        switch_target="operator", readback_target="pid",
        rollback_readback_target="oldpid",
    )


def _ledger(home, scope, index, status):
    row = dict(scope.as_dict())
    row.update({
        "path": "m1-operator", "status": status,
        "release_scope": scope.as_dict(),
        "release_scope_ref": scope.scope_ref,
        "candidate_authority": scope.candidate_authority,
        "release_run_id": "owner-review-v1",
        "release_request_ref": "e" * 64,
        "release_canon_revision": "canon-source/v1:test",
    })
    path = home / ("operator-owner-main-release-" + str(index) * 20 + ".json")
    path.write_text(json.dumps({"schema": 1, "paths": {"m1-operator": row}}))
    path.chmod(0o600)
    return path


def _host(home):
    host = object.__new__(FixedOperatorHost)
    host.home = home
    host.source_root = home
    host.plist = home / "operator.plist"
    return host


def test_multiple_inflight_ledgers_fail_with_specific_safe_reason(tmp_path):
    scope = _scope()
    paths = [_ledger(tmp_path, scope, 1, "PREPARED"),
             _ledger(tmp_path, scope, 2, "CUTOVER")]
    before = [p.read_bytes() for p in paths]
    host = _host(tmp_path)
    code = "RELEASE_MULTIPLE_INFLIGHT"
    with pytest.raises(OperatorHostDenied, match="^" + code + "$"):
        host.select_release_registry(
            tmp_path / "operator-only-release-registry.json", scope=scope)
    assert [p.read_bytes() for p in paths] == before
    assert _safe_failure_reason(OperatorHostDenied(code)) == code


def test_multiple_verified_loaded_ledgers_fail_with_specific_safe_reason(tmp_path):
    scope = _scope()
    paths = [_ledger(tmp_path, scope, 1, "VERIFIED"),
             _ledger(tmp_path, scope, 2, "VERIFIED")]
    before = [p.read_bytes() for p in paths]
    host = _host(tmp_path)
    loaded_script = (
        tmp_path / "Library/Application Support/AI-Foundation"
        / "operator-release-staging" / scope.scope_ref
        / "candidate/scripts/operator_server.py"
    )
    host.plist.write_bytes(plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": ["/opt/homebrew/bin/python3.12", str(loaded_script)],
    }))
    host.plist.chmod(0o600)
    host.verified_current_release = lambda record: True
    code = "RELEASE_MULTIPLE_VERIFIED_LOADED"
    with pytest.raises(OperatorHostDenied, match="^" + code + "$"):
        host.select_release_registry(
            tmp_path / "operator-only-release-registry.json", scope=scope)
    assert [p.read_bytes() for p in paths] == before
    assert _safe_failure_reason(OperatorHostDenied(code)) == code
