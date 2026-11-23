"""Fixed shared 9B inventory and admission; no real host/model operations."""
import io
import json
import pytest
from ai_foundation import shared_ollama9b_adapter as subject
from ai_foundation.shared_ollama9b_adapter import (
    MODEL, MODEL_DIGEST, PREFIX, SharedOllama9BDiscovery, SharedOllama9BExecution)
from ai_foundation.host_compute_lease import HostComputeLease, HostComputeBusy

class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *args): pass

def test_only_exact_installed_9b_digest_is_same_host_chat_insurance(monkeypatch):
    monkeypatch.setattr(subject, "_dedicated_backend_idle", lambda: True)
    for model, digest, online in ((MODEL, MODEL_DIGEST, True),
                                 (MODEL, "0" * 64, False),
                                 ("qwen3.5:4b", MODEL_DIGEST, False)):
        def open_catalog(req, **kwargs):
            assert req.full_url in {
                "http://127.0.0.1:11434/api/tags",
                "http://127.0.0.1:11434/api/ps"}
            return Response(json.dumps({"models": [
                {"name": model, "digest": digest}]}).encode())
        row = SharedOllama9BDiscovery(opener=open_catalog)()[0]
        if online:
            assert row.health == "ONLINE" and row.same_host is True
            assert row.binding == PREFIX + ":general"
            assert row.capabilities == row.roles == ("CHAT",)
        else:
            assert row.health == "UNAVAILABLE" and not row.capabilities


def test_shared_9b_discovery_excludes_busy_and_cold_unadmitted(monkeypatch):
    resident = [{"name": "unrelated-resident", "digest": "other"}]
    calls = []
    def opener(req, **kwargs):
        calls.append(req.full_url)
        models = ([{"name": MODEL, "digest": MODEL_DIGEST}]
                  if req.full_url.endswith("/api/tags") else resident)
        return Response(json.dumps({"models": models}).encode())
    monkeypatch.setattr(subject, "_dedicated_backend_idle", lambda: True)
    monkeypatch.setattr(subject, "admit_local_9b", lambda: (False, "MEMORY_PRESSURE"))
    discovery = SharedOllama9BDiscovery(opener=opener)
    busy = discovery()[0]
    assert busy.health == "UNAVAILABLE" and not busy.active
    assert busy.capabilities == ()
    assert busy.reason == "OTHER_LOCAL_MODEL_OR_BACKEND_RESIDENT"
    resident.clear()
    cold = discovery()[0]
    assert cold.health == "UNAVAILABLE" and cold.reason == "MEMORY_PRESSURE"
    assert not cold.active
    monkeypatch.setattr(subject, "admit_local_9b", lambda: (True, subject.AVAILABLE))
    assert discovery()[0].health == "ONLINE"
    assert all(u.endswith(("/api/ps", "/api/tags")) for u in calls)

def test_shared_9b_respects_lease_alias_and_resident_model_without_eviction(
        tmp_path, monkeypatch):
    lease = HostComputeLease(tmp_path / "owner" / "compute.lock")
    resident = [{"name": MODEL, "digest": MODEL_DIGEST}]
    calls = []
    def send(req, **kwargs):
        calls.append(req.full_url)
        if req.full_url.endswith("/api/tags"):
            return Response(json.dumps({"models": [
                {"name": MODEL, "digest": MODEL_DIGEST}]}).encode())
        if req.full_url.endswith("/api/ps"):
            return Response(json.dumps({"models": resident}).encode())
        assert req.full_url == "http://127.0.0.1:11434/v1/chat/completions"
        assert json.loads(req.data)["model"] == MODEL
        return Response(json.dumps({"choices": [
            {"message": {"role": "assistant", "content": "OK"}}]}).encode())
    monkeypatch.setattr(subject, "_dedicated_backend_idle", lambda: True)
    execution = SharedOllama9BExecution(opener=send, host_lease=lease)
    with lease.hold():
        with pytest.raises(HostComputeBusy):
            execution.chat("fixed public test")
    assert calls == []
    assert execution.chat("fixed public test") == "OK"
    assert len(calls) == 3
    with pytest.raises(ValueError):
        execution.chat("fixed public test", model="code-agent")
    assert len(calls) == 3
    resident[:] = [{"name": "unrelated-model", "digest": "other"}]
    with pytest.raises(HostComputeBusy):
        execution.chat("fixed public test")
    assert not any(url.endswith("/completions") for url in calls[3:])

def test_cold_start_reuses_existing_capacity_gate_and_never_loads_when_denied(
        tmp_path, monkeypatch):
    calls = []
    def send(req, **kwargs):
        calls.append(req.full_url)
        return Response(json.dumps({"models": [] if req.full_url.endswith("/api/ps")
            else [{"name": MODEL, "digest": MODEL_DIGEST}]}).encode())
    monkeypatch.setattr(subject, "_dedicated_backend_idle", lambda: True)
    monkeypatch.setattr(subject, "admit_local_9b", lambda: (False, "MEMORY_PRESSURE"))
    execution = SharedOllama9BExecution(
        opener=send, host_lease=HostComputeLease(tmp_path / "owner" / "compute.lock"))
    with pytest.raises(HostComputeBusy, match="MEMORY_PRESSURE"):
        execution.chat("fixed public test")
    assert len(calls) == 2
    monkeypatch.setattr(subject, "_dedicated_backend_idle", lambda: False)
    with pytest.raises(HostComputeBusy, match="OTHER_LOCAL_MODEL_OR_BACKEND_RESIDENT"):
        execution.chat("fixed public test")
    assert len(calls) == 4

def test_loopback_transport_does_not_follow_redirects():
    assert subject._NoRedirect().redirect_request(None, None, 302, "", {}, "http://remote/") is None
