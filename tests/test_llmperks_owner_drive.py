"""No-network owner Drive app-file handoff acceptance.

This tests the exact host-writer interface without a Google account or token.
The real existing Keychain/drive.file adapter remains PR #481, not mocked into
the production worker or KLM read-only credential.
"""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256

import pytest

from ai_foundation.llmperks_discovery import SourceInvalid, fingerprint
from ai_foundation.llmperks_ranking import FULL_URL
from ai_foundation.llmperks_service_routes import project_service_model_routes
from ai_foundation.llmperks_owner_drive import (
    make_handoff, handoff_to_owner_drive, MAX_DRIVE_TEXT,
)

LEDGER = {
    "deployment_state": "RESEARCH_ONLY",
    "default_route_enabled": False,
    "services": [
        {"id": "groq", "name": "Groq API", "route_kind": "INFERENCE_API",
         "enabled": False},
        {"id": "opencode-zen-free", "name": "OpenCode tool", "route_kind": "DEVELOPMENT_TOOL",
         "enabled": False},
    ],
}


def data():
    catalog = {
        "schema": "llmperks-full-claims-v1", "source_url": FULL_URL,
        "publisher_snapshot": "2026-11-09T21:53:10.556Z",
        "models": {
            "https://llmperks.com/example/strong-model": {
                "name": "Strong Model",
                "model_page": "https://llmperks.com/example/strong-model",
                "reasoning": True, "capabilities_claimed": ["reasoning", "coding"],
                "aa_intelligence": 42.5, "gpqa_diamond": 93.1,
                "endpoints_claimed": [
                    {"provider": "groq", "provider_model_id_claimed": "example/strong",
                     "context_claimed": "128000"},
                    {"provider": "opencode", "provider_model_id_claimed": "strong-free",
                     "context_claimed": "n/a"},
                ],
            },
        },
        "publisher_totals_not_verified": {"models": 1, "endpoints": 2, "providers": 2},
        "authority": "RESEARCH_ONLY_NO_EXECUTION_OR_BILLING",
    }
    catalog["sha256"] = fingerprint(catalog)
    return catalog, project_service_model_routes(LEDGER, catalog)


class Owner:
    runtime = "/owner-private/consented-drive"
    def __init__(self):
        self.probes = 0

    def probe(self):
        self.probes += 1
        return True


class ExistingStore:
    def __init__(self):
        self.files = {}
        self.create_calls = 0
        self.read_calls = 0

    def _find(self, digest):
        return digest[:16] if digest in self.files else None

    def create_once(self, digest, content):
        self.create_calls += 1
        assert sha256(content.encode()).hexdigest() == digest
        assert 0 < len(content.encode()) <= MAX_DRIVE_TEXT
        assert digest not in self.files
        self.files[digest] = content
        return digest[:16]

    def read(self, file_id):
        self.read_calls += 1
        return next((v for k, v in self.files.items() if k[:16] == file_id), None)


@contextmanager
def locked(_private_runtime):
    yield


def test_stable_one_note_per_snapshot_without_credentials_or_provider_write():
    catalog, projection = data()
    digest, body = make_handoff(catalog, projection)
    assert sha256(body.encode()).hexdigest() == digest
    assert make_handoff(catalog, projection) == (digest, body)
    assert "NO EXECUTION AUTHORITY" in body
    assert "UNTRUSTED" in body
    assert "GPQA Diamond descending" in body
    assert "groq: 1 observed model/API IDs" in body
    assert "model ID" not in body or "provider" in body
    assert len(body.encode()) <= MAX_DRIVE_TEXT


def test_inspection_is_read_only_then_write_once_and_repeat_is_idempotent():
    catalog, projection = data()
    owner, store = Owner(), ExistingStore()
    ports = (owner, store, locked)
    inspected = handoff_to_owner_drive(catalog, projection, owner_ports=ports, write=False)
    assert inspected["status"] == "RESEARCH_NOTE_NOT_STORED"
    assert store.create_calls == 0
    first = handoff_to_owner_drive(catalog, projection, owner_ports=ports, write=True)
    assert first["status"] == "RESEARCH_NOTE_CREATED_READBACK_VERIFIED"
    assert owner.probes == 2 and store.create_calls == 1 and store.read_calls == 1
    again = handoff_to_owner_drive(catalog, projection, owner_ports=ports, write=True)
    assert again["status"] == "RESEARCH_NOTE_ALREADY_VERIFIED"
    assert store.create_calls == 1
    assert again["sha256"] == first["sha256"]
    assert all(result["execution_authorized"] is False
               for result in (inspected, first, again))


def test_existing_text_mismatch_fails_closed_without_duplicate_write():
    catalog, projection = data()
    owner, store = Owner(), ExistingStore()
    digest, body = make_handoff(catalog, projection)
    store.files[digest] = body + " CORRUPTED"
    with pytest.raises(SourceInvalid, match="OWNER_DRIVE_READBACK_UNVERIFIED"):
        handoff_to_owner_drive(catalog, projection,
                               owner_ports=(owner, store, locked), write=True)
    assert store.create_calls == 0


def test_projection_mismatch_rejected_before_any_owner_port_called():
    catalog, projection = data()
    tampered = deepcopy(projection)
    tampered["source_sha256"] = "0" * 64
    owner = Owner()
    with pytest.raises(SourceInvalid, match="UNTRUSTED_OR_MISMATCHED"):
        handoff_to_owner_drive(catalog, tampered,
                               owner_ports=(owner, ExistingStore(), locked), write=True)
    assert owner.probes == 0


def test_write_requires_explicit_boolean():
    catalog, projection = data()
    with pytest.raises(ValueError, match="EXPLICIT_WRITE_MODE_REQUIRED"):
        handoff_to_owner_drive(catalog, projection, write=1)
