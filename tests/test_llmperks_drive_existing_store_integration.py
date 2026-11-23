"""Cross-Draft integration: LLMPerks → actual PR #481 create-once store.

No account, no key, no outbound network. We inject only the HTTP transport,
not a substitute for the production CreateOnlyDriveTextPlanStore semantics.
"""
from contextlib import nullcontext
from types import SimpleNamespace

from ai_foundation.development_drive_plan import APP_KEY
from ai_foundation.development_drive_text import CreateOnlyDriveTextPlanStore
from ai_foundation import development_drive_runtime, development_drive_text_runtime
from ai_foundation.llmperks_discovery import fingerprint
from ai_foundation.llmperks_owner_drive import handoff_to_owner_drive, make_handoff
from ai_foundation.llmperks_ranking import FULL_URL
from ai_foundation.llmperks_service_routes import project_service_model_routes


class FakeDriveHTTP:
    def __init__(self):
        self.contents = {}
        self.create_count = 0
        self.media_reads = 0

    def call(self, service, method, path, *, query=None, body=None):
        assert (service, method, path) == ("drive", "GET", "/files")
        digest = query["q"].split("value='", 1)[1].split("'", 1)[0]
        if digest not in self.contents:
            return {"files": []}
        return {"files": [{
            "id": digest[:24],
            "mimeType": "text/plain",
            "appProperties": {APP_KEY: digest},
        }]}

    def create_text(self, digest, content):
        self.create_count += 1
        assert digest not in self.contents
        self.contents[digest] = content
        return digest[:24]

    def read_text(self, file_id):
        self.media_reads += 1
        return next(value for digest, value in self.contents.items()
                    if digest[:24] == file_id)


def catalog_and_projection():
    cat = {
        "schema": "llmperks-full-claims-v1",
        "source_url": FULL_URL,
        "publisher_snapshot": "2026-11-09T21:53:10.556Z",
        "models": {
            "https://llmperks.com/example/model": {
                "name": "Model",
                "model_page": "https://llmperks.com/example/model",
                "reasoning": True, "capabilities_claimed": ["reasoning"],
                "aa_intelligence": 42.1, "gpqa_diamond": 91.0,
                "endpoints_claimed": [{
                    "provider": "groq",
                    "provider_model_id_claimed": "example/model",
                    "context_claimed": "128000",
                }],
            },
        },
        "publisher_totals_not_verified": {"models": 1, "endpoints": 1, "providers": 1},
        "authority": "RESEARCH_ONLY_NO_EXECUTION_OR_BILLING",
    }
    cat["sha256"] = fingerprint(cat)
    ledger = {
        "deployment_state": "RESEARCH_ONLY", "default_route_enabled": False,
        "services": [{"id": "groq", "name": "Groq",
                      "route_kind": "INFERENCE_API", "enabled": False}],
    }
    return cat, project_service_model_routes(ledger, cat)


def test_real_owner_drive_store_is_used_and_produces_exact_media_readback(monkeypatch, tmp_path):
    catalog, projection = catalog_and_projection()
    http = FakeDriveHTTP()
    owner = SimpleNamespace(runtime=tmp_path, probe=lambda: True)
    # Actual library store performs the digest metadata lookup, content/ID
    # confirmation, and independent raw-media GET itself.
    actual_store = CreateOnlyDriveTextPlanStore(http)
    monkeypatch.setattr(development_drive_text_runtime, "text_port",
                        lambda: (owner, actual_store))
    monkeypatch.setattr(development_drive_runtime, "_exclusive_acceptance",
                        lambda runtime: nullcontext())
    first = handoff_to_owner_drive(catalog, projection, write=True)
    second = handoff_to_owner_drive(catalog, projection, write=True)
    digest, text = make_handoff(catalog, projection)
    assert first["status"] == "RESEARCH_NOTE_CREATED_READBACK_VERIFIED"
    assert second["status"] == "RESEARCH_NOTE_ALREADY_VERIFIED"
    assert actual_store._find(digest) == digest[:24]
    assert http.contents[digest] == text
    assert http.create_count == 1
    assert http.media_reads >= 3
    assert first["execution_authorized"] is False


def test_real_owner_drive_store_refuses_mismatched_existing_content(monkeypatch, tmp_path):
    from ai_foundation.llmperks_discovery import SourceInvalid
    import pytest
    catalog, projection = catalog_and_projection()
    digest, text = make_handoff(catalog, projection)
    http = FakeDriveHTTP()
    http.contents[digest] = text + "tampered"
    owner = SimpleNamespace(runtime=tmp_path, probe=lambda: True)
    monkeypatch.setattr(development_drive_text_runtime, "text_port",
                        lambda: (owner, CreateOnlyDriveTextPlanStore(http)))
    monkeypatch.setattr(development_drive_runtime, "_exclusive_acceptance",
                        lambda runtime: nullcontext())
    with pytest.raises(SourceInvalid, match="OWNER_DRIVE_READBACK_UNVERIFIED"):
        handoff_to_owner_drive(catalog, projection, write=True)
    assert http.create_count == 0
