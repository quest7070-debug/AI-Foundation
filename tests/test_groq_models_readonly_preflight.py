"""Groq read-only preflight has no inference, secrets output or billing admission."""
import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError

path = Path(__file__).resolve().parents[1] / "scripts/groq_models_readonly_preflight.py"
spec = importlib.util.spec_from_file_location("groq_models_readonly_preflight", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Result:
    status = 200
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass
    def read(self, _limit):
        return self.payload


class Opener:
    def __init__(self, ids):
        self.calls = []
        self.ids = ids
    def __call__(self, req, *, timeout):
        self.calls.append((req.full_url, req.get_method(), timeout))
        assert req.full_url == module.MODELS_URL
        assert req.get_method() == "GET"
        assert timeout == 8
        assert "Authorization" in req.headers
        return Result(json.dumps({
            "data": [{"id": item} for item in self.ids]}).encode())


def test_single_readonly_get_never_grants_billing_authority():
    opener = Opener(["openai/gpt-oss-20b"])
    status = module.verify_models("gsk_"+"A"*25, opener=opener)
    assert status == {
        "status": "KEY_ACCEPTED_MODEL_LISTED",
        "model": "openai/gpt-oss-20b",
        "billing_verified": False,
        "network_calls": 1, "inference_calls": 0}
    assert len(opener.calls) == 1
    assert "gsk_" not in str(status)


def test_invalid_key_and_unpinned_model_send_no_requests():
    opener = Opener([])
    assert module.verify_models("bad", opener=opener)["status"] == "INVALID_KEY_FORMAT"
    assert module.verify_models("gsk_"+"Z"*25, opener=opener,
                                model="unreviewed-new-model")["status"] == "MODEL_NOT_PINNED"
    assert opener.calls == []


def test_model_absent_is_not_a_live_route():
    opener = Opener(["different-model"])
    assert module.verify_models("gsk_"+"A"*25, opener=opener) == {
        "status": "MODEL_NOT_LISTED",
        "model": "openai/gpt-oss-20b",
        "billing_verified": False,
        "network_calls": 1, "inference_calls": 0}


def test_http_error_is_redacted():
    def denied(req, *, timeout):
        raise HTTPError(req.full_url, 401, "secret-containing-provider-body",
                        None, io.BytesIO(b"gsk_SUPER_SECRET"))
    status = module.verify_models("gsk_"+"B"*25, opener=denied)
    assert status == {"status": "HTTP_ERROR", "http_status": 401,
                      "billing_verified": False, "inference_calls": 0,
                      "error_class": "NON_JSON_DENIAL"}
    assert "gsk_" not in str(status)


class Store:
    def __init__(self, items):
        self.items = dict(items)
    def available(self, binding):
        return binding in self.items
    def load(self, binding):
        return self.items[binding]


def test_stage_missing_finds_only_one_registered_free_groq_key(tmp_path):
    from ai_foundation.provider_registry import SQLiteProviderRegistry
    db = tmp_path / "providers.sqlite"
    registry = SQLiteProviderRegistry(db)
    registry.upsert("llm:groq:adopted", "GROQ", "FREE", "UNVERIFIED")
    registry.upsert("llm:groq:paid", "GROQ", "PAID", "ONLINE")
    registry.upsert("llm:other:1", "MISTRAL", "FREE", "ONLINE")
    store = Store({"llm:groq:adopted": "gsk_" + "A"*24,
                   "llm:groq:paid": "gsk_" + "B"*24})
    result = module.resolve_staged_or_registered_binding(store, db)
    assert result == ("llm:groq:adopted", "REGISTERED_KEY")
    assert module.resolve_staged_or_registered_binding(store, None) == (
        None, "STAGED_KEY_MISSING_REGISTRY_UNLOCATED")


def test_multiple_registered_free_groq_keys_do_not_guess_account(tmp_path):
    from ai_foundation.provider_registry import SQLiteProviderRegistry
    db = tmp_path / "providers.sqlite"
    registry = SQLiteProviderRegistry(db)
    registry.upsert("llm:groq:a", "GROQ", "FREE", "UNVERIFIED")
    registry.upsert("llm:groq:b", "GROQ", "FREE", "UNVERIFIED")
    store = Store({"llm:groq:a": "gsk_" + "A"*24,
                   "llm:groq:b": "gsk_" + "B"*24})
    assert module.resolve_staged_or_registered_binding(store, db) == (
        None, "MULTIPLE_REGISTERED_GROQ_KEYS")
    store.items[module.STAGED_BINDING] = "gsk_" + "C"*24
    assert module.resolve_staged_or_registered_binding(store, db) == (
        module.STAGED_BINDING, "STAGED_KEY")


def test_registry_lookup_does_not_create_unexpected_database(tmp_path):
    missing = tmp_path / "no_registry.sqlite"
    assert module.resolve_staged_or_registered_binding(Store({}), missing) == (
        None, "STAGED_KEY_MISSING_REGISTRY_UNLOCATED")
    assert not missing.exists()


def test_permission_error_code_without_echoing_provider_message():
    payload = json.dumps({"error": {
        "type": "permissions_error", "code": "model_permission_blocked_project",
        "message": "private path /Users/name/password=secret"}}).encode()
    def denied(req, *, timeout):
        return (_ for _ in ()).throw(HTTPError(
            req.full_url, 403, "forbidden",
            {"Content-Type": "application/json"}, io.BytesIO(payload)))
    status = module.verify_models("gsk_" + "A"*24, opener=denied)
    assert status["error_class"] == "PROVIDER_JSON"
    assert status["error_code"] == "model_permission_blocked_project"
    assert status["error_type"] == "permissions_error"
    assert status["inference_calls"] == 0
    assert "Users" not in str(status) and "secret" not in str(status)


def test_generic_forbidden_without_code():
    def denied(req, *, timeout):
        raise HTTPError(req.full_url, 403, "forbidden",
                        {"Content-Type": "application/json"},
                        io.BytesIO(b'{"error":{"message":"Forbidden"}}'))
    status = module.verify_models("gsk_" + "A"*24, opener=denied)
    assert status["error_class"] == "GENERIC_FORBIDDEN"
    assert "error_type" not in status and "error_code" not in status


def test_html_403_is_not_misclassified_as_model_permission():
    def denied(req, *, timeout):
        raise HTTPError(req.full_url, 403, "forbidden",
                        {"Content-Type": "text/html"},
                        io.BytesIO(b'<html><h1>access denied</h1></html>'))
    status = module.verify_models("gsk_" + "A"*24, opener=denied)
    assert status["error_class"] == "HTML_GATEWAY_DENIAL"
    assert "error_type" not in status and "error_code" not in status
