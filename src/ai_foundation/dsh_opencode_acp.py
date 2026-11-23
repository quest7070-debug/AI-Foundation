"""Official DSH ACP transport STAGING for OpenCode; no extra agent framework.

DSH manages the subprocess and ACP lifetime. Foundation retains account/model
admission, exact-model egress, Guard, resource lease and Draft publication.
This module only prepares a private, deny-all DSH profile patch. It never
launches DSH/OpenCode or changes a model, account policy, or Guard receipt.
"""
from __future__ import annotations

import json
import re
from pathlib import PurePosixPath

_FREE = re.compile(r"opencode/[a-z0-9][a-z0-9.-]{1,127}-free\Z")


def _private_path(value):
    if (type(value) is not str or not value.startswith("/")
            or not 3 <= len(value) <= 1024
            or value in ("/tmp", "/Users", "/private", "/private/tmp")
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or any(part in ("", ".", "..") for part in value[1:].split("/"))
            or str(PurePosixPath(value)) != value):
        raise ValueError("DSH_ACP_ABSOLUTE_PRIVATE_PATH_REQUIRED")
    return value


def first_admitted_ranked_candidate(ranked, admitted):
    """Select first host-admitted exact model in external quality order.

    'ranked' is an untrusted/free-model plugin output. 'admitted' MUST be
    supplied from Foundation's independently verified account + Guard route,
    never assembled from the plugin catalog/zero-cost label or this method.
    No score table, availability probes, network access or auto-retries.
    """
    if (type(ranked) not in (list, tuple) or len(ranked) > 64
            or type(admitted) not in (list, tuple, set, frozenset)
            or len(admitted) > 64
            or any(type(x) is not str or not _FREE.fullmatch(x)
                   for x in admitted)):
        raise ValueError("DSH_ACP_TRUSTED_ADMISSION_REQUIRED")
    # Validate the entire untrusted list *before* returning a good match.
    # A malicious/stale trailing entry must not be silently ignored.
    if any(type(item) is not str or len(item) > 160 for item in ranked):
        raise ValueError("DSH_ACP_RANKING_INVALID")
    approved = set(admitted)
    for item in ranked:
        if item in approved and _FREE.fullmatch(item):
            return item
    return None



def first_admitted_llmperks_opencode(ranking, admitted):
    """Rank measured GPQA first, then AA-scored candidates lacking GPQA.

    PR #526 supplies publisher research, not model availability or payment
    authority. Only the independently host-admitted exact Free IDs are usable.
    Missing GPQA must never be silently invented or remove AA-scored Free
    candidates, such as current OpenCode DeepSeek V4.1 Flash.
    """
    if (type(ranking) is not dict
            or ranking.get("schema") != "llmperks-reasoning-rankings-v1"
            or ranking.get("publisher_claims_only") is not True
            or ranking.get("execution_authorized") is not False):
        raise ValueError("DSH_ACP_RANKING_INVALID")
    gpqa = ranking.get("gpqa_diamond")
    aa = ranking.get("aa_intelligence")
    if type(gpqa) is not dict or (aa is not None and type(aa) is not dict):
        raise ValueError("DSH_ACP_RANKING_INVALID")
    source = "https://llmperks.com/llms-full.txt"
    gpqa_snapshot = gpqa.get("source_snapshot")
    def collect(result, metric):
        rows = result.get("ranked")
        if (result.get("schema") != "llmperks-score-ranked-research-v1"
                or result.get("metric") != metric
                or result.get("source_url") != source
                or result.get("execution_authorized") is not False
                or type(rows) is not list or len(rows) > 100
                or (aa is not None and gpqa_snapshot is not None
                    and result.get("source_snapshot") != gpqa_snapshot)):
            raise ValueError("DSH_ACP_RANKING_INVALID")
        ids = []
        for index, item in enumerate(rows, 1):
            if (type(item) is not dict
                    or type(item.get("rank")) is not int
                    or item["rank"] != index
                    or type(item.get("provider_model_ids_claimed")) is not list
                    or len(item["provider_model_ids_claimed"]) > 40):
                raise ValueError("DSH_ACP_RANKING_INVALID")
            for endpoint in item["provider_model_ids_claimed"]:
                if type(endpoint) is not dict:
                    raise ValueError("DSH_ACP_RANKING_INVALID")
                if endpoint.get("provider") != "opencode":
                    continue
                model = endpoint.get("model_id")
                if type(model) is not str or not 1 <= len(model) <= 127:
                    raise ValueError("DSH_ACP_RANKING_INVALID")
                candidate = "opencode/" + model
                if _FREE.fullmatch(candidate) and candidate not in ids:
                    ids.append(candidate)
        return ids
    top = collect(gpqa, "gpqa_diamond")
    secondary = collect(aa, "aa_intelligence") if aa is not None else []
    ordered = top + [x for x in secondary if x not in top]
    return first_admitted_ranked_candidate(ordered, admitted)


def staged_ranked_dsh_opencode_acp(*, ranking, admitted, opencode_binary,
                                  seatbelt_profile, private_home):
    """Use existing ACP backend and the top already-approved ranked model."""
    selected = first_admitted_llmperks_opencode(ranking, admitted)
    if selected is None:
        return {"candidate_model": None, "execution_authorized": False,
                "stage": "HOLD_NO_ADMITTED_RANKED_FREE_MODEL"}
    return staged_dsh_opencode_acp(
        opencode_binary=opencode_binary, seatbelt_profile=seatbelt_profile,
        private_home=private_home, candidate_model=selected)


def staged_dsh_opencode_acp(*, opencode_binary, seatbelt_profile,
                            private_home, candidate_model):
    """Build a DSH profile patch; NEVER returns execution authorization.

    Call only with a single exact model chosen by the trusted host from
    independently approved candidates. A '-free' suffix alone is not proof
    of no-charge routing. The profile must be mounted only after the host
    verifies the binary digest, native Seatbelt WAN-denial, parent child-cwd
    scope, account budget and exact egress/attempt gates from PR #512.
    """
    binary = _private_path(opencode_binary)
    seatbelt = _private_path(seatbelt_profile)
    home = _private_path(private_home)
    if (home in (binary, seatbelt) or type(candidate_model) is not str
            or _FREE.fullmatch(candidate_model) is None):
        raise ValueError("DSH_ACP_REVIEWED_FREE_MODEL_REQUIRED")

    # Official OpenCode 2 config: permissions (tool requests) and policies
    # (provider, integration, tool hard-denials) are distinct. A named Free
    # model does not authorize actual inference or billing.
    child = {
        "model": candidate_model,
        "small_model": candidate_model,
        "update": "disable",
        "plugins": [],
        "mcp": {},
        "permissions": [{"action": "*", "resource": "*", "effect": "deny"}],
        "policies": [
            {"action": "provider.use", "resource": "*", "effect": "deny"},
            {"action": "provider.use", "resource": "opencode", "effect": "allow"},
            *({"action": a, "resource": "*", "effect": "deny"} for a in (
                "tool.use", "plugin.use", "integration.connect",
                "integration.use", "mcp.use", "skill.use", "websearch.use")),
        ],
        "experimental": {"subagent_depth": 0, "background_compaction": False},
    }
    env = {
        "HOME": home,
        "XDG_CONFIG_HOME": home + "/config",
        "XDG_STATE_HOME": home + "/state",
        "XDG_DATA_HOME": home + "/data",
        "XDG_CACHE_HOME": home + "/cache",
        "OPENCODE_CONFIG_DIR": home + "/config/opencode",
        "OPENCODE_DB": home + "/state/opencode.db",
        "OPENCODE_DISABLE_FILEWATCHER": "true",
        "OPENCODE_CONFIG_CONTENT": json.dumps(child, separators=(",", ":")),
        "OPENCODE_PURE": "1",
        "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
        "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
        "OPENCODE_DISABLE_MODELS_FETCH": "true",
        "OPENCODE_DISABLE_PRUNE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "NO_COLOR": "1",
    }
    # One official DSH ACP provider & one official delegation tool; no new
    # scheduler, child ACP client, model picker, retry loop or session DB.
    patch = [{
        "insert": [
            {"id": "foundation-opencode-acp",
             "name": "@deepseek-ai/dsh-subagent-acp",
             "config": {
                 "providerName": "foundation-opencode",
                 "command": "/usr/bin/sandbox-exec",
                 # The reviewed OpenCode 2.2.5 CLI supports "acp" here;
                 # global --pure is rejected by the pinned offline image.
                 # OPENCODE_PURE=1 already prohibits external plugins.
                 "args": ["-f", seatbelt, binary, "acp"],
                 "permission": "reject",
                 "env": env,
             }},
            {"id": "foundation-tool-subagent-opencode",
             "name": "@deepseek-ai/dsh-tool-subagent",
             "config": {
                 "provider": "foundation-opencode",
                 "toolName": "subagent_opencode",
                 "maxDepth": "provider-managed",
             }},
        ]
    }]
    return {
        "patch_json": json.dumps(patch, indent=2),
        "candidate_model": candidate_model,
        "execution_authorized": False,
    }
