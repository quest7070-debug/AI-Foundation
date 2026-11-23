"""Reuse the pinned, already installed shared M1 9B without model installation."""
import json
import socket
from urllib import request
from .host_compute_lease import HostComputeLease, HostComputeBusy
from .klm_9b_handler import MODEL, MODEL_DIGEST
from .klm_compute_admission import AVAILABLE, RESOURCE_UNKNOWN, admit_local_9b
from .local_compute_registry import LocalComputeCandidate
from .openai_local_adapter import OpenAILocalExecution

PREFIX = "local:ollama-shared9b"
BASE = "http://127.0.0.1:11434"

class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

_OPENER = request.build_opener(request.ProxyHandler({}), _NoRedirect())

def _local_json(opener, path):
    if path not in {"/api/tags", "/api/ps"}:
        raise ValueError("FIXED_SHARED_9B_PROBE_REQUIRED")
    with opener(request.Request(BASE + path), timeout=2) as response:
        raw = response.read(262145)
    if len(raw) > 262144:
        raise ValueError("SHARED_9B_REPLY_TOO_LARGE")
    value = json.loads(raw)
    if (type(value) is not dict or type(value.get("models")) is not list
            or len(value["models"]) > 128
            or any(type(row) is not dict for row in value["models"])):
        raise ValueError("SHARED_9B_INVENTORY_UNVERIFIED")
    return value["models"]

def _pinned(row):
    return (row.get("name", row.get("model")) == MODEL
            and row.get("digest") == MODEL_DIGEST)

def _dedicated_backend_idle():
    try:
        with socket.create_connection(("127.0.0.1", 11436), timeout=.2):
            return False
    except ConnectionRefusedError:
        return True
    except OSError:
        return False

class SharedOllama9BDiscovery:
    def __init__(self, *, opener=None):
        self.open = opener or _OPENER.open

    def __call__(self):
        # Discovery is presentation and selection, never an inference grant.
        # Match the same installed/runtime/CPU/RAM conditions that execution
        # rechecks under HostComputeLease. Do not advertise a model as ONLINE
        # merely because its bytes are installed while another model is loaded.
        def unavailable(reason):
            return (LocalComputeCandidate(
                PREFIX + ":general", health="UNAVAILABLE", active=False,
                capabilities=(), roles=(), model=MODEL, slot="general",
                reason=reason, same_host=True),)
        try:
            if not any(_pinned(row) for row in _local_json(self.open, "/api/tags")):
                return unavailable("PINNED_9B_NOT_VERIFIED")
            resident = _local_json(self.open, "/api/ps")
            if (len(resident) > 1 or any(not _pinned(row) for row in resident)
                    or not _dedicated_backend_idle()):
                return unavailable("OTHER_LOCAL_MODEL_OR_BACKEND_RESIDENT")
            if not resident:
                admitted, reason = admit_local_9b()
                if admitted is not True or reason != AVAILABLE:
                    return unavailable(reason if reason in {
                        "CPU_PRESSURE", "MEMORY_PRESSURE"} else RESOURCE_UNKNOWN)
        except (OSError, ValueError, TypeError):
            return unavailable("SHARED_9B_STATE_UNVERIFIED")
        return (LocalComputeCandidate(
            PREFIX + ":general", health="ONLINE", active=True,
            capabilities=("CHAT",), roles=("CHAT",), model=MODEL,
            slot="general", characteristics=("EXISTING M1 9B",), same_host=True),)

class SharedOllama9BExecution(OpenAILocalExecution):
    def __init__(self, *, opener=None, host_lease=None):
        super().__init__(
            BASE,
            allowed_hosts=("127.0.0.1",),
            alias_to_model={"general": MODEL},
            opener=opener or _OPENER.open,
            timeout=900,
            request_defaults={'reasoning_effort': 'none'}
        )
        self.host_lease = HostComputeLease() if host_lease is None else host_lease
        self.calls = 0

    def _admit(self):
        # Recheck exact installed bytes and live residency under the existing
        # lease. Never evict another shared model or duplicate a worker backend.
        try:
            tags = _local_json(self.open, "/api/tags")
            running = _local_json(self.open, "/api/ps")
        except (OSError, ValueError, TypeError):
            raise HostComputeBusy("SHARED_9B_STATE_UNVERIFIED") from None
        if not any(_pinned(row) for row in tags):
            raise HostComputeBusy("PINNED_9B_NOT_VERIFIED")
        if (len(running) > 1 or any(not _pinned(row) for row in running)
                or not _dedicated_backend_idle()):
            raise HostComputeBusy("OTHER_LOCAL_MODEL_OR_BACKEND_RESIDENT")
        if not running:
            allowed, reason = admit_local_9b()
            if allowed is not True or reason != AVAILABLE:
                raise HostComputeBusy(reason if reason in {
                    "CPU_PRESSURE", "MEMORY_PRESSURE"} else RESOURCE_UNKNOWN)

    def chat_payload(self, payload, model=None):
        # Validate alias before taking the lease or issuing any probe.
        self._model(model or "general")
        with self.host_lease.hold():
            self._admit()
            self.calls += 1

            # Determine whether to use the native /api/chat endpoint.
            use_native = (
                "tools" not in payload and
                sum(len(m.get("content", "")) for m in payload.get("messages", [])) > 4096
            )
            if use_native:
                # Resolve the concrete model name.
                alias_key = model or "general"
                model_name = self.models[alias_key]

                request_body = {
                    "model": model_name,
                    "messages": payload.get("messages", []),
                    "stream": False,
                    "think": False,
                    "options": {"num_ctx": 16384, "num_predict": 16384}
                }
                req = request.Request(
                    f"{BASE}/api/chat",
                    data=json.dumps(request_body).encode(),
                    method="POST",
                    headers={"Content-Type": "application/json"}
                )
                with self.open(req, timeout=self.timeout) as resp:
                    raw = resp.read(self.max + 1)
                if len(raw) > self.max:
                    raise ValueError("SHARED_9B_REPLY_TOO_LARGE")
                data = json.loads(raw)

                # Convert native response to OpenAI-compatible shape.
                content = ""
                if isinstance(data, dict):
                    # Prefer 'message' field if present.
                    if "message" in data:
                        content = data["message"].get("content", "")
                    elif "content" in data:
                        content = data.get("content", "")
                finish_reason = "stop" if data.get("done_reason") == "stop" else "length"
                prompt_tokens = data.get("prompt_eval_count", 0)
                completion_tokens = data.get("eval_count", 0)
                total_tokens = prompt_tokens + completion_tokens

                return {
                    "choices": [{
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": finish_reason
                    }],
                    "model": model_name,
                    "usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens
                    }
                }

            # Fallback to the standard OpenAI‑compatible endpoint.
            return super().chat_payload(payload, model=model or "general")

    def chat(self, prompt, model=None):
        return super().chat(prompt, model=model or "general")
