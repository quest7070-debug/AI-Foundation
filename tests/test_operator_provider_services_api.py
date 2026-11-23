"""Operator service-first JSON must never disclose any native credentials."""
import json
import threading
from urllib.request import urlopen

from ai_foundation.operator_server import OperatorApplication, serve
from ai_foundation.provider_service_view import (
    AccountView, CredentialConnection, ProjectView, ServiceView,
)


class Settings:
    def services(self):
        conn = CredentialConnection(
            reference="key:0123456789abcdef", tier="FREE",
            observed_health="UNVERIFIED", stored=True,
            approved_for_model=False,
            admission_reason="NO_ACCOUNT_BILLING_EVIDENCE",
            models=("openai/gpt-oss-20b",))
        return (ServiceView(
            "GROQ", 1, 0, (AccountView(
                "unverified-account:abcd", False, (ProjectView(
                    "unverified-project:abcd", False, (conn,)),)),)),)


def test_provider_services_payload_is_service_first_and_secret_free():
    app = OperatorApplication.__new__(OperatorApplication)
    app.settings = Settings()
    data = app.provider_services_payload()
    assert data["schema"] == 1
    item = data["provider_services"][0]
    assert item["provider"] == "GROQ"
    assert item["credentials"] == 1
    assert item["approved_connections"] == 0
    assert item["accounts"][0]["projects"][0]["credentials"][0]["stored"]
    serialized = json.dumps(data)
    assert "gsk_" not in serialized
    assert "llm:groq:" not in serialized


def test_loopback_readonly_service_endpoint():
    app = OperatorApplication.__new__(OperatorApplication)
    app.settings = Settings()
    srv = serve(app)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen("http://127.0.0.1:" + str(srv.server_port) +
                     "/api/provider-services") as response:
            data = json.loads(response.read())
        assert response.status == 200
        assert data["provider_services"][0]["approved_connections"] == 0
    finally:
        srv.shutdown()
        srv.server_close()


def test_harness_readonly_status_has_no_provider_key_or_activation():
    app = OperatorApplication.__new__(OperatorApplication)
    app.settings = Settings()
    data = app.harness_service_payload()
    assert data == {"schema": 2, "manager": "FOUNDATION_HARNESS",
                    "services": [], "state": "NOT_CONFIGURED"}


def test_loopback_harness_services_api_is_readonly():
    app = OperatorApplication.__new__(OperatorApplication)
    app.settings = Settings()
    srv = serve(app)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen("http://127.0.0.1:" + str(srv.server_port) +
                     "/api/harness-services") as response:
            data = json.loads(response.read())
        assert response.status == 200
        assert data["manager"] == "FOUNDATION_HARNESS"
        assert "gsk_" not in json.dumps(data)
    finally:
        srv.shutdown()
        srv.server_close()


def test_operator_lists_multiple_services_without_key_or_account_details():
    class MultiServiceSettings(Settings):
        def harness_services_status(self):
            return {
                "schema": 2, "manager": "FOUNDATION_HARNESS",
                "services": [
                    {"service": "GROQ", "state": "HOLD_NO_APPROVED_FREE_CONNECTION"},
                    {"service": "NVIDIA", "state": "ADAPTER_REQUIRED"},
                ],
                "default_fallback": "LOCAL_HARNESS_9B",
                "runtime_enabled": False,
            }
    app = OperatorApplication.__new__(OperatorApplication)
    app.settings = MultiServiceSettings()
    data = app.harness_service_payload()
    assert [x["service"] for x in data["services"]] == ["GROQ", "NVIDIA"]
    assert not data["runtime_enabled"]
    assert "gsk_" not in json.dumps(data)
    assert "llm:groq:" not in json.dumps(data)


def test_operator_explicit_research_ledger_passes_to_existing_harness_status():
    class ResearchSettings(Settings):
        def harness_services_status(self, research_ledger=None):
            if research_ledger is None:
                raise AssertionError("trusted research ledger missing")
            assert research_ledger["deployment_state"] == "RESEARCH_ONLY"
            return {
                "schema": 2, "manager": "FOUNDATION_HARNESS",
                "services": [], "research_candidates": [
                    {"service_id": "jules", "integration_kind":
                     "CLOUD_DEVELOPMENT_SERVICE",
                     "execution_authorized": False}],
                "runtime_enabled": False,
            }
    app = OperatorApplication.__new__(OperatorApplication)
    app.settings = ResearchSettings()
    app.research_ledger = {"deployment_state": "RESEARCH_ONLY",
                           "services": []}
    snapshot = app.harness_service_payload()
    assert [x["service_id"] for x in snapshot["research_candidates"]] == ["jules"]
    assert not snapshot["runtime_enabled"]
