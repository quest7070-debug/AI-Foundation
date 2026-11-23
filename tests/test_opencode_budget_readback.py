"""Tests for local OpenCode Console budget readback (all network is loopback)."""
import http.server
import json
import threading
from unittest.mock import patch

import pytest
from ai_foundation.opencode_budget_readback import (
    probe_local_signed_in_budget, summarize_workspace_budget,
)

WORKSPACE = "ws_owner_selected_123"
LOCATION = "/Users/fixture/public-project"


def budget(**overrides):
    item = {
        "id": "policy-1", "limit": 0, "spent": 0, "scope": "combined",
        "per": "set", "coverage": "all", "shared": True,
        "picked": False, "models": [], "vendors": [],
        "resetsAt": 1793491200000,
    }
    item.update(overrides)
    return item


def payload(budgets=None, workspace=WORKSPACE, wrapped=True, location=LOCATION):
    data = {"workspace": {"id": workspace, "name": "Secret workspace",
                          "usageURL": "https://private.example"},
            "budgets": [budget()] if budgets is None else budgets}
    if wrapped:
        data = {"location": {"directory": location}, "data": data}
    return json.dumps(data).encode()


def test_zero_workspace_all_spend_is_observed_but_never_approved():
    result = summarize_workspace_budget(
        payload(), expected_workspace_id=WORKSPACE,
        expected_location_directory=LOCATION)
    assert result["workspace_zero_budget_observed"] is True
    assert result["account_independently_attested"] is False
    assert result["auto_recharge_verified"] is False
    assert result["go_extra_usage_verified"] is False
    assert result["execution_authorized"] is False
    assert "Secret workspace" not in repr(result)


@pytest.mark.parametrize("candidate", [
    budget(limit=1), budget(limit=-1),
    budget(limit=True), budget(limit=float("nan")),
    budget(scope="each"), budget(per="model"),
    budget(coverage="models"), budget(shared=False),
    budget(picked=True), budget(models=[{"modelID": "paid"}]),
    budget(vendors=["Any vendor"]), budget(inputPriceAtLeast=2),
])
def test_partial_budget_or_ambiguous_limit_never_proves_no_charge(candidate):
    result = summarize_workspace_budget(
        payload(budgets=[candidate]), expected_workspace_id=WORKSPACE,
        expected_location_directory=LOCATION)
    assert result["workspace_zero_budget_observed"] is False
    assert result["execution_authorized"] is False


@pytest.mark.parametrize("raw", [
    b'null', b'{"data":null}', b'{}',
    b'{"data":{"workspace":{"id":"wrong"},"budgets":[]}}',
    b'{"data":{"workspace":{"id":"ws_owner_selected_123"},'
    b'"budgets":[{"coverage":"all","coverage":"models"}]}}',
    b"x" * 65537,
])
def test_missing_stale_and_ambiguous_data_fail_closed(raw):
    assert summarize_workspace_budget(
        raw, expected_workspace_id=WORKSPACE,
        expected_location_directory=LOCATION)["workspace_zero_budget_observed"] is False



@pytest.mark.parametrize("budgets,reason", [
    ([budget(id="zero"), budget(id="other", limit=2)],
     "CONFLICTING_WORKSPACE_ALL_SPEND_BUDGET"),
    ([budget(id="zero"), budget(id="other", limit=float("nan"))],
     "CONFLICTING_WORKSPACE_ALL_SPEND_BUDGET"),
    ([budget(id="zero"), budget(id="duplicate")],
     "AMBIGUOUS_WORKSPACE_ALL_SPEND_BUDGET"),
])
def test_multiple_workspace_all_spend_rows_never_select_favorable_zero(budgets, reason):
    result = summarize_workspace_budget(
        payload(budgets=budgets), expected_workspace_id=WORKSPACE,
        expected_location_directory=LOCATION)
    assert result["reason"] == reason
    assert result["workspace_zero_budget_observed"] is False
    assert result["execution_authorized"] is False


def test_mismatched_selected_workspace_rejects_even_qualifying_budget():
    assert summarize_workspace_budget(
        payload(workspace="another"), expected_workspace_id=WORKSPACE,
        expected_location_directory=LOCATION
    )["reason"] == "ACCOUNT_SCOPE_OR_BUDGETS_MISSING"


def test_loopback_probe_reads_only_local_usage_endpoint():
    requests = []
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            requests.append(self.path)
            data = payload()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = probe_local_signed_in_budget(
            port=server.server_port, expected_workspace_id=WORKSPACE,
            location_directory=LOCATION)
        assert result["workspace_zero_budget_observed"] is True
        assert result["account_independently_attested"] is False
        assert requests == [
            "/api/experimental/usage/limits?"
            "location%5Bdirectory%5D=%2FUsers%2Ffixture%2Fpublic-project"
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_no_port_discovery_or_external_network_when_port_untrusted():
    for port in ("http://example.com", 0, -1, 65536, True):
        assert probe_local_signed_in_budget(
            port=port, expected_workspace_id=WORKSPACE,
            location_directory=LOCATION
        )["status"] == "HOLD_UNVERIFIED"


def _synthetic_eligible_review():
    """Only a unit fixture; never an owner-account attestation."""
    import time
    from ai_foundation.next_service_preflight import OpenCodeReviewEvidence
    return OpenCodeReviewEvidence(
        model="opencode/hy4-flash-free",
        observed_at=time.time(), official_model_revision_sha256="a" * 64,
        free_model_priced_zero=True, actual_account_free=True,
        no_payment_method=False, no_prepaid_balance=False,
        auto_recharge_off=True, go_extra_usage_off=True,
        paid_fallback_off=True, background_model_free_only=True,
        isolated_binary_verified=True, private_server_verified=True,
        no_shared_auth_or_project=True, native_sandbox_verified=True,
        exact_model_network_enforcement_verified=True,
        workspace_zero_budget_verified=False,
    )


def test_existing_owner_zero_budget_observation_binds_without_new_router():
    from ai_foundation.next_service_preflight import opencode_readiness
    from ai_foundation.opencode_budget_readback import bind_observed_budget_to_review
    from ai_foundation.opencode_harness_service import reviewed_opencode_execution_factory

    calls = []
    def probe(*, port, expected_workspace_id, location_directory):
        calls.append(("read", port, expected_workspace_id, location_directory))
        return summarize_workspace_budget(payload(), expected_workspace_id=expected_workspace_id,
            expected_location_directory=location_directory)
    def attest(*, port, expected_workspace_id, location_directory):
        calls.append(("owner", port, expected_workspace_id, location_directory))
        return True
    review, state = bind_observed_budget_to_review(
        _synthetic_eligible_review(), port=4096,
        expected_workspace_id=WORKSPACE, location_directory=LOCATION,
        probe=probe,
        attest_owner_workspace=attest)
    assert state == "OWNER_ZERO_BUDGET_BOUND"
    assert review.workspace_zero_budget_verified is True
    assert calls == [
        ("read", 4096, WORKSPACE, LOCATION),
        ("owner", 4096, WORKSPACE, LOCATION),
    ]
    # Existing preflight and host port, no new provider selector or grant.
    assert opencode_readiness(review)["stage"] == "PREPARED_FOR_HOST_REVIEW"
    assert opencode_readiness(review)["execution_authorized"] is False
    class CLI:
        def run_bounded_public_code(self, *, model, prompt):
            raise AssertionError("synthetic test must never invoke a model")
    assert callable(reviewed_opencode_execution_factory(port=CLI(), review=review))


@pytest.mark.parametrize("budget_raw,attested,reason", [
    (payload(budgets=[budget(limit=4)]), True, "ZERO_WORKSPACE_BUDGET_NOT_OBSERVED"),
    (payload(workspace="other_workspace"), True, "ZERO_WORKSPACE_BUDGET_NOT_OBSERVED"),
    (payload(), False, "OWNER_ACCOUNT_BINDING_REQUIRED"),
])
def test_unattested_or_changed_budget_never_preserves_stale_approval(
        budget_raw, attested, reason):
    from dataclasses import replace
    from ai_foundation.opencode_budget_readback import bind_observed_budget_to_review
    from ai_foundation.next_service_preflight import opencode_readiness
    review=replace(_synthetic_eligible_review(), workspace_zero_budget_verified=True)
    calls=[]
    def owner(*, port, expected_workspace_id, location_directory):
        assert location_directory == LOCATION
        calls.append("owner")
        return attested
    updated, result=bind_observed_budget_to_review(
        review, port=4096, expected_workspace_id=WORKSPACE,
        location_directory=LOCATION,
        probe=lambda **_:summarize_workspace_budget(
            budget_raw,expected_workspace_id=WORKSPACE,
        expected_location_directory=LOCATION),
        attest_owner_workspace=owner)
    assert result==reason
    assert updated.workspace_zero_budget_verified is False
    assert opencode_readiness(updated)["stage"]=="HOLD_UNVERIFIED"
    assert calls == (["owner"] if reason == "OWNER_ACCOUNT_BINDING_REQUIRED" else [])


def test_budget_binding_never_attempts_account_lookup_with_unknown_source():
    from ai_foundation.opencode_budget_readback import bind_observed_budget_to_review
    review, state=bind_observed_budget_to_review(
        _synthetic_eligible_review(), port=0,
        expected_workspace_id=WORKSPACE, location_directory=LOCATION,
        probe=lambda **_: pytest.fail("untrusted port attempted a GET"),
        attest_owner_workspace=lambda **_: pytest.fail("owner called"))
    assert state == "OWNER_ACCOUNT_BINDING_REQUIRED"
    assert review.workspace_zero_budget_verified is False


@pytest.mark.parametrize("directory", [
    "", "/", "relative/path", "/Users/fixture/../other",
    "/Users/fixture//public", "/Users/fixture/./public",
    "/Users/fixture/public\\nHEADER: leak", "http://example.com/public",
])
def test_unpinned_location_never_reads_or_binds_budget(directory):
    from ai_foundation.opencode_budget_readback import bind_observed_budget_to_review
    assert probe_local_signed_in_budget(
        port=4096, expected_workspace_id=WORKSPACE,
        location_directory=directory)["reason"] == "PINNED_LOCATION_REQUIRED"
    review, state = bind_observed_budget_to_review(
        _synthetic_eligible_review(), port=4096,
        expected_workspace_id=WORKSPACE, location_directory=directory,
        probe=lambda **_: pytest.fail("unreviewed location made local GET"),
        attest_owner_workspace=lambda **_: pytest.fail("unreviewed location attested"))
    assert state == "OWNER_ACCOUNT_BINDING_REQUIRED"
    assert review.workspace_zero_budget_verified is False


@pytest.mark.parametrize("response", [
    payload(location="/Users/fixture/foreign-project"),
    payload(wrapped=False),
    json.dumps({"data": json.loads(payload())["data"]}).encode(),
    json.dumps({"location": {"directory": LOCATION, "extra": "untrusted"},
                "data": json.loads(payload())["data"]}).encode(),
    json.dumps({"location": {"directory": LOCATION}, "data": None}).encode(),
])
def test_real_api_envelope_rejects_foreign_or_missing_location(response):
    result = summarize_workspace_budget(
        response, expected_workspace_id=WORKSPACE,
        expected_location_directory=LOCATION)
    assert result["workspace_zero_budget_observed"] is False
    assert result["execution_authorized"] is False


def test_original_locationless_fixture_would_be_false_positive():
    # Same workspace ID is insufficient without the official location envelope.
    raw = payload(wrapped=False)
    assert summarize_workspace_budget(
        raw, expected_workspace_id=WORKSPACE,
        expected_location_directory=LOCATION)["reason"] == (
            "LOCATION_OR_RESPONSE_ENVELOPE_MISMATCH")


def test_one_shot_cli_outputs_only_unattested_local_status(monkeypatch, capsys):
    import io
    import sys
    import ai_foundation.opencode_budget_readback as mod
    call = []
    def offline(**kwargs):
        call.append(kwargs)
        return summarize_workspace_budget(payload(),
            expected_workspace_id=WORKSPACE,
            expected_location_directory=LOCATION)
    monkeypatch.setattr(mod, "probe_local_signed_in_budget", offline)
    source = json.dumps({"port": 3001, "expected_workspace_id": WORKSPACE,
                         "location_directory": LOCATION}).encode()
    monkeypatch.setattr(sys, "stdin",
                        type("Input", (), {"buffer": io.BytesIO(source)})())
    assert mod.main() == 0
    line = capsys.readouterr().out
    result = json.loads(line)
    assert result["workspace_zero_budget_observed"] is True
    assert result["account_independently_attested"] is False
    assert result["execution_authorized"] is False
    assert WORKSPACE not in line and LOCATION not in line
    assert call == [{"port": 3001, "expected_workspace_id": WORKSPACE,
                     "location_directory": LOCATION}]
    monkeypatch.setattr(sys, "stdin",
                        type("Input", (), {"buffer": io.BytesIO(b'{}')})())
    assert mod.main() == 2
    assert json.loads(capsys.readouterr().out)["execution_authorized"] is False
