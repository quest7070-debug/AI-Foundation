"""Routing stays backend-neutral and does not repeat local discovery within one decision."""
from ai_foundation.compute_routing import ComputeRouter
from ai_foundation.core import CanonContract, Decision, TaskPlan
from ai_foundation.inference_service import GuardedInferenceService
from ai_foundation.local_compute_registry import LocalComputeCandidate, LocalComputeRegistry
from ai_foundation.settings_service import SettingsService


class Secrets:
    def available(self, binding):
        return True


class Probe:
    pass


def setup(tmp_path):
    observed = []
    def discover():
        observed.append("local-discovery")
        return (LocalComputeCandidate(
            "local:test", health="ONLINE", capabilities=("CHAT",),
            model="owned-gguf", slot="local-general",
        ),)
    service = SettingsService(tmp_path, Probe(), Secrets(),
                              local_compute=LocalComputeRegistry(discover))
    return service, observed


def test_all_capability_routes_share_one_fresh_local_inventory(tmp_path):
    settings, seen = setup(tmp_path)
    result = settings.optimize_all_routes()
    assert len(result) == len(settings.ROUTE_FUNCTIONS)
    assert seen == ["local-discovery"]
    assert settings.route("CHAT").primary == "local:test"
    assert settings.route("CODE").primary is None


def test_one_route_choice_uses_one_local_inventory_for_matching_and_policy(tmp_path):
    settings, seen = setup(tmp_path)
    settings.optimize_all_routes()
    before = len(seen)
    route = ComputeRouter(settings, settings.local_compute).choose("CHAT")
    assert (route.binding, route.kind, route.execution_slot) == (
        "local:test", "LOCAL", "local-general",
    )
    assert len(seen) == before + 1
    # Unshared standalone SettingsService callers still discover a live snapshot.
    assert settings.choose_route("CHAT") == "local:test"
    assert len(seen) == before + 2


def test_free_remote_and_local_only_share_selector_without_paid_fallback(tmp_path):
    settings, seen = setup(tmp_path)
    settings.registry.upsert(
        "free-provider", "GROQ", "FREE", "ONLINE", 80, "1m", 70, "1d",
        endpoint="https://api.example.invalid", model="approved-model",
        protocol="openai-chat", capabilities=("CHAT",),
    )
    settings.registry.upsert(
        "paid-provider", "GROQ", "PAID", "ONLINE", 100, "1m", 100, "1d",
        endpoint="https://api.example.invalid", model="approved-model",
        protocol="openai-chat", capabilities=("CHAT",),
    )
    settings.optimize_all_routes()
    router = ComputeRouter(settings, settings.local_compute)
    before = len(seen)
    route = router.choose("CHAT")
    assert (route.binding, route.kind) == ("free-provider", "CLOUD")
    assert len(seen) == before + 1
    private = router.choose("CHAT", local_required=True)
    assert (private.binding, private.kind) == ("local:test", "LOCAL")
    assert len(seen) == before + 2
    offline = router.choose("CHAT", exclude=("free-provider", "local:test"))
    assert offline.binding is None
    assert len(seen) == before + 3


def test_inference_activity_label_does_not_trigger_second_local_discovery(tmp_path):
    settings, seen = setup(tmp_path)
    settings.optimize_all_routes()
    class Guard:
        def preflight(self, plan, canon):
            return Decision.LOCAL_ONLY
    class Local:
        def chat(self, text, model=None):
            assert model == "local-general"
            return "ok"
    router = ComputeRouter(settings, settings.local_compute)
    infer = GuardedInferenceService(Guard(), router, Local())
    before = len(seen)
    outcome = infer.run(
        TaskPlan("run", "compute", "llm", text="hello", canon_revision="r", effect_id="e"),
        CanonContract("owner", "r"),
    )
    assert (outcome.status, outcome.route_kind, outcome.result) == (
        "VERIFIED_COMPLETE", "LOCAL", "ok",
    )
    assert len(seen) == before + 1


def test_prefer_local_skips_policy_and_remote_provider_work(tmp_path):
    settings, seen = setup(tmp_path)
    settings.optimize_all_routes()
    def forbidden(*a, **k):
        raise AssertionError("local preference should short-circuit policy")
    settings.choose_route = forbidden
    before = len(seen)
    route = ComputeRouter(settings, settings.local_compute).choose("CHAT", prefer_local=True)
    assert (route.binding, route.kind) == ("local:test", "LOCAL")
    assert len(seen) == before + 1
