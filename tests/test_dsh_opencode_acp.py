"""One focused no-model contract: official DSH ACP delegates, no charge grant."""
import json
import pytest
from ai_foundation.dsh_opencode_acp import (
    first_admitted_ranked_candidate, staged_dsh_opencode_acp,
    first_admitted_llmperks_opencode, staged_ranked_dsh_opencode_acp,
)


def stage(**kw):
    args = dict(
        opencode_binary="/opt/homebrew/bin/opencode",
        seatbelt_profile="/private/foundation/deny-wan.sb",
        private_home="/private/foundation/opencode-child",
        candidate_model="opencode/hy4-flash-free",
    )
    args.update(kw)
    return staged_dsh_opencode_acp(**args)


def test_official_dsh_child_is_private_and_no_tools_no_paid_fallback():
    report = stage()
    assert report["execution_authorized"] is False
    provider, tool = json.loads(report["patch_json"])[0]["insert"]
    assert provider["name"] == "@deepseek-ai/dsh-subagent-acp"
    assert tool["name"] == "@deepseek-ai/dsh-tool-subagent"
    assert tool["config"] == {
        "provider": "foundation-opencode", "toolName": "subagent_opencode",
        "maxDepth": "provider-managed",
    }
    cfg = provider["config"]
    assert cfg["permission"] == "reject"
    assert cfg["args"][-1:] == ["acp"]
    assert cfg["args"][:3] == [
        "-f", "/private/foundation/deny-wan.sb", "/opt/homebrew/bin/opencode"]
    env = cfg["env"]
    assert env["HOME"] == "/private/foundation/opencode-child"
    assert env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    assert env["OPENCODE_DISABLE_EXTERNAL_SKILLS"] == "1"
    assert env["OPENCODE_PURE"] == "1"
    assert env["OPENCODE_DB"] == "/private/foundation/opencode-child/state/opencode.db"
    assert env["OPENCODE_DISABLE_FILEWATCHER"] == "true"
    assert env["OPENCODE_DISABLE_MODELS_FETCH"] == "true"
    assert all(not k.startswith(("OPENAI_", "ANTHROPIC_", "GROQ_", "CODEX_"))
               for k in env)
    oc = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert oc["model"] == "opencode/hy4-flash-free"
    assert oc["update"] == "disable"
    assert "autoupdate" not in oc
    assert oc["permissions"] == [
        {"action": "*", "resource": "*", "effect": "deny"}]
    assert oc["plugins"] == [] and oc["mcp"] == {}
    rules = oc["policies"]
    assert rules[0:2] == [
        {"action": "provider.use", "resource": "*", "effect": "deny"},
        {"action": "provider.use", "resource": "opencode", "effect": "allow"}]
    assert all(rule["effect"] == "deny" for rule in rules[2:])
    assert {x["action"] for x in rules[2:]} >= {
        "tool.use", "plugin.use", "websearch.use", "integration.connect"}


def test_ranked_candidates_cannot_approve_own_free_claims():
    top = "opencode/top-reasoner-free"
    fallback = "opencode/hy4-flash-free"
    ranked = [top, fallback]
    assert first_admitted_ranked_candidate(ranked, [fallback]) == fallback
    assert first_admitted_ranked_candidate(ranked, []) is None
    assert first_admitted_ranked_candidate(ranked, [top, fallback]) == top
    assert stage(candidate_model=top)["candidate_model"] == top


@pytest.mark.parametrize("kwargs", [
    {"candidate_model": "opencode/paid"},
    {"candidate_model": "opencode/free"},
    {"candidate_model": "openrouter/glm-5.3-flash-free"},
    {"candidate_model": "opencode/wrong-free\nSECRET=1"},
    {"seatbelt_profile": "/tmp"},
    {"opencode_binary": "opencode"},
    {"private_home": "/"},
    {"private_home": "/private/work/../x"},
    {"private_home": "/private/foundation/child\nOPENCODE_DB=/tmp/leak"},
    {"seatbelt_profile": "/private/foundation/deny\r-wan.sb"},
    {"opencode_binary": "/opt/homebrew/bin/open\tcode"},
    {"private_home": "/private/foundation/child\x7f"},
])
def test_unreviewed_models_and_host_paths_fail_without_launch(kwargs):
    with pytest.raises(ValueError, match="DSH_ACP_"):
        stage(**kwargs)


@pytest.mark.parametrize("ranked, admitted", [
    (["opencode/paid"], ["opencode/paid"]),
    (["opencode/foo-free"], ["opencode/paid"]),
    (["opencode/ok-free", None], ["opencode/ok-free"]),
    ("opencode/ok-free", ["opencode/ok-free"]),
])
def test_invalid_rankings_and_unapproved_models_never_route(ranked, admitted):
    with pytest.raises(ValueError, match="DSH_ACP_"):
        first_admitted_ranked_candidate(ranked, admitted)


def test_llmperks_gpqa_rank_is_only_an_ordering_hint_for_admitted_models():
    def row(rank, model):
        return {"rank": rank, "provider_model_ids_claimed":
                [{"provider": "opencode", "model_id": model}]}
    ranking = {
        "schema": "llmperks-reasoning-rankings-v1",
        "publisher_claims_only": True, "execution_authorized": False,
        "gpqa_diamond": {
            "schema": "llmperks-score-ranked-research-v1",
            "metric": "gpqa_diamond",
            "source_url": "https://llmperks.com/llms-full.txt",
            "execution_authorized": False,
            "ranked": [row(1, "top-reasoner-free"),
                       row(2, "hy4-flash-free")],
        },
    }
    assert first_admitted_llmperks_opencode(ranking, []) is None
    admitted = ["opencode/hy4-flash-free"]
    assert first_admitted_llmperks_opencode(ranking, admitted) == admitted[0]
    selected = staged_ranked_dsh_opencode_acp(
        ranking=ranking, admitted=admitted,
        opencode_binary="/opt/homebrew/bin/opencode",
        seatbelt_profile="/private/foundation/deny-wan.sb",
        private_home="/private/foundation/opencode-child")
    assert selected["execution_authorized"] is False
    assert selected["candidate_model"] == admitted[0]
    provider = json.loads(selected["patch_json"])[0]["insert"][0]
    assert json.loads(provider["config"]["env"]["OPENCODE_CONFIG_CONTENT"])["model"] == admitted[0]
    assert staged_ranked_dsh_opencode_acp(
        ranking=ranking, admitted=[],
        opencode_binary="/opt/homebrew/bin/opencode",
        seatbelt_profile="/private/foundation/deny-wan.sb",
        private_home="/private/foundation/opencode-child")["stage"] == (
            "HOLD_NO_ADMITTED_RANKED_FREE_MODEL")
    ranking["execution_authorized"] = True
    with pytest.raises(ValueError, match="RANKING_INVALID"):
        first_admitted_llmperks_opencode(ranking, admitted)
