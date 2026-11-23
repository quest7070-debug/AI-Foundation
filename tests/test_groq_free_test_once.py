"""One-shot Groq E2E: owner selection is required before any key/network read."""
import importlib.util
import json
from pathlib import Path

from ai_foundation.free_route_admission import SQLiteFreeRouteAdmission
from ai_foundation.groq_once_ledger import SQLiteGroqOnceLedger
from ai_foundation.provider_registry import SQLiteProviderRegistry
from ai_foundation.cloud_execution import CloudResponse

file = Path(__file__).resolve().parents[1] / "scripts/groq_free_test_once.py"
spec = importlib.util.spec_from_file_location("groq_free_test_once", file)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


class Secret:
    def __init__(self, present=True):
        self.present=present
        self.reads=0
    def available(self, binding):
        return self.present
    def load(self, binding):
        self.reads+=1
        return "fake-secret"


class Transport:
    def __init__(self):
        self.calls=[]
    def send(self, provider, secret, payload):
        self.calls.append((provider, payload))
        assert secret=="fake-secret"
        assert provider=="GROQ"
        assert payload["model"]=="openai/gpt-oss-20b"
        assert payload["service_tier"]=="on_demand"
        assert payload["max_completion_tokens"]==16
        assert "tools" not in payload
        assert len(payload["messages"])==1
        return CloudResponse(200,{},json.dumps({
            "choices":[{"message":{"content":"FOUNDATION_OK"}}]}))


def setup(tmp_path):
    registry = SQLiteProviderRegistry(tmp_path/"providers.sqlite")
    registry.upsert("llm:groq:test","GROQ","FREE","UNVERIFIED",
                    endpoint="https://api.groq.com/openai/v1/chat/completions",
                    model="openai/gpt-oss-20b",protocol="openai-chat",
                    capabilities=("CHAT",))
    admission=SQLiteFreeRouteAdmission(tmp_path/"admission.sqlite",
                                       clock=lambda:1000)
    return registry,admission,SQLiteGroqOnceLedger(tmp_path/'groq-one-shot.sqlite', clock=lambda:1000)


def select(registry, admission):
    row = registry.credential("llm:groq:test")
    admission.select(row, account_alias="fixture-account",
                     project_alias="fixture-project")


def test_unselected_route_no_key_read_no_network(tmp_path):
    registry,admission,ledger=setup(tmp_path)
    secret=Secret()
    transport=Transport()
    outcome=subject.run_one(registry,admission,secret,transport,binding="llm:groq:test",ledger=ledger)
    assert outcome=={"status":"FREE_ROUTE_DENIED",
                     "reason":"NOT_MANUALLY_SELECTED","sent":False}
    assert secret.reads==0 and transport.calls==[]


def test_single_public_fixture_only_after_manual_selection(tmp_path):
    registry,admission,ledger=setup(tmp_path)
    select(registry,admission)
    registry.observe("llm:groq:test", health="ONLINE")
    secret=Secret()
    transport=Transport()
    result=subject.run_one(registry,admission,secret,transport,binding="llm:groq:test",ledger=ledger)
    assert result=={"status":"VERIFIED_PUBLIC_FIXTURE","sent":True}
    assert secret.reads==1 and len(transport.calls)==1
    assert "fake-secret" not in repr(result)
    # Even another process may not retry the same test/binding on quota errors.
    second = subject.run_one(registry,admission,secret,transport,
                             binding="llm:groq:test",ledger=ledger)
    assert second == {"status":"ONE_SHOT_ALREADY_CLAIMED","sent":False}
    assert secret.reads==1 and len(transport.calls)==1


def test_paid_or_missing_key_remains_denied(tmp_path):
    registry,admission,ledger=setup(tmp_path)
    select(registry,admission)
    registry.upsert("llm:groq:test","GROQ","PAID","ONLINE",
                    endpoint="https://api.groq.com/openai/v1/chat/completions",
                    model="openai/gpt-oss-20b",protocol="openai-chat",
                    capabilities=("CHAT",))
    secret=Secret()
    transport=Transport()
    assert not subject.run_one(registry,admission,secret,transport,
                               binding="llm:groq:test",ledger=ledger)["sent"]
    assert secret.reads==0 and transport.calls==[]


def test_manually_selected_free_service_not_disabled_by_legacy_expiry(tmp_path):
    registry,admission,ledger=setup(tmp_path)
    select(registry,admission)
    admission.clock=lambda:1500
    secret=Secret()
    transport=Transport()
    outcome=subject.run_one(registry,admission,secret,transport,
                            binding="llm:groq:test",ledger=ledger)
    assert outcome["status"]=="VERIFIED_PUBLIC_FIXTURE"
    assert secret.reads==1 and len(transport.calls)==1


def test_restarted_admission_keeps_one_shot_claim_and_never_retries(tmp_path):
    registry, admission, ledger = setup(tmp_path)
    select(registry, admission)
    registry.observe("llm:groq:test", health="ONLINE")
    meta = registry.credential("llm:groq:test")
    assert ledger.claim(binding=meta["binding"], model=meta["model"],
                        endpoint=meta["endpoint"])
    # Simulates a new process opening the same durable one-shot DB.
    second = SQLiteGroqOnceLedger(tmp_path/"groq-one-shot.sqlite",
                                  clock=lambda:1000)
    secret=Secret()
    transport=Transport()
    result=subject.run_one(registry,admission,secret,transport,
                           binding="llm:groq:test",ledger=second)
    assert result == {"status":"ONE_SHOT_ALREADY_CLAIMED","sent":False}
    assert secret.reads==0 and not transport.calls


def test_free_route_must_be_accepted_before_attempt_claim(tmp_path):
    registry,admission,ledger=setup(tmp_path)
    secret=Secret()
    transport=Transport()
    result=subject.run_one(registry,admission,secret,transport,
                           binding="llm:groq:test",ledger=ledger)
    assert result["status"]=="FREE_ROUTE_DENIED"
    assert ledger.status()=="NEVER_CLAIMED"
    assert secret.reads==0 and not transport.calls


def test_service_first_selection_excludes_paid_and_other_providers(tmp_path):
    registry, admission, ledger = setup(tmp_path)
    assert subject.free_groq_connections(registry) == ("llm:groq:test",)
    registry.upsert("llm:mistral:free", "MISTRAL", "FREE", "UNVERIFIED")
    registry.upsert("llm:groq:paid", "GROQ", "PAID", "UNVERIFIED")
    assert subject.free_groq_connections(registry) == ("llm:groq:test",)
    registry.upsert("llm:groq:other-account", "GROQ", "FREE", "UNVERIFIED")
    assert set(subject.free_groq_connections(registry)) == {
        "llm:groq:test", "llm:groq:other-account"}


def test_unverified_free_is_allowed_but_failed_health_preserves_claim(tmp_path):
    registry, admission, ledger = setup(tmp_path)
    select(registry, admission)
    secret, transport = Secret(), Transport()
    for health in ("RATE_LIMITED", "DOWN", "CREDENTIAL_ERROR"):
        registry.observe("llm:groq:test", health=health)
        result = subject.run_one(
            registry, admission, secret, transport,
            binding="llm:groq:test", ledger=ledger)
        assert result == {"status": "PROVIDER_NOT_READY", "sent": False}
        assert ledger.status() == "NEVER_CLAIMED"
    assert secret.reads == 0 and transport.calls == []
    registry.observe("llm:groq:test", health="UNVERIFIED")
    assert subject.run_one(
        registry, admission, secret, transport,
        binding="llm:groq:test", ledger=ledger)["status"] == "VERIFIED_PUBLIC_FIXTURE"
    assert secret.reads == 1 and len(transport.calls) == 1
