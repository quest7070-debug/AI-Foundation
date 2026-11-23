"""Rank LLMPerks publisher-claimed free reasoning models; no route authority.

The full text feed has capabilities, AA Intelligence Index, GPQA Diamond and
provider/model IDs. Scores are third-party observations, not independently
measured performance or proof of a no-charge account. Missing scores are
excluded from that ranking rather than guessed.
"""
from __future__ import annotations

from datetime import datetime
import re
from urllib import request

from .llmperks_discovery import SourceInvalid, fingerprint

FULL_URL = "https://llmperks.com/llms-full.txt"
MAX_FULL_BYTES = 524288
MODEL_URL = re.compile(r"https://(?:www\.)?llmperks\.com/[a-z0-9-]+/[a-z0-9-]+\Z")
PROVIDER_ENDPOINT = re.compile(
    r"- ([a-z][a-z0-9-]{0,50}): id=([^;\r\n]{1,200}); "
    r"context=([^;\r\n]{1,40})(?:; url=([^\r\n]{1,512}))?\Z"
)
TOTAL = re.compile(r"# Total: (\d+) models, (\d+) free endpoints, (\d+) providers online\Z")
METRIC = re.compile(r"^AA Intelligence Index: ([0-9]+(?:\.[0-9]+)?)(?:; GPQA Diamond: ([0-9]+(?:\.[0-9]+)?)%)?$")
TIMESTAMP = re.compile(r"^# Snapshot: (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z)$")
RANK_METRICS = ("aa_intelligence", "gpqa_diamond")


def _date(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceInvalid("FULL_SNAPSHOT_INVALID") from exc


def _build_model(lines):
    if not lines:
        return None
    title = lines[0][3:]
    url = developer = capabilities = None
    aa = gpqa = None
    endpoints = []
    for line in lines[1:]:
        if line.startswith("URL: "):
            if url is not None:
                raise SourceInvalid("FULL_MODEL_URL_DUPLICATE")
            url = line[5:]
        elif line.startswith("Developer: "):
            if developer is not None:
                raise SourceInvalid("FULL_DEVELOPER_DUPLICATE")
            developer = line[11:][:120]
        elif line.startswith("Type: "):
            if capabilities is not None:
                raise SourceInvalid("FULL_TYPE_DUPLICATE")
            cap_match = re.search(r"capabilities: ([^;]+)", line)
            capabilities = [x.strip() for x in cap_match.group(1).split(",")] if cap_match else []
        elif line.startswith("AA Intelligence Index: "):
            if aa is not None:
                raise SourceInvalid("FULL_METRIC_DUPLICATE")
            match = METRIC.fullmatch(line)
            if not match:
                raise SourceInvalid("FULL_METRIC_FORMAT_CHANGED")
            aa = float(match.group(1))
            gpqa = float(match.group(2)) if match.group(2) else None
            if aa > 100 or (gpqa is not None and gpqa > 100):
                raise SourceInvalid("FULL_METRIC_OUT_OF_RANGE")
        elif line.startswith("- "):
            match = PROVIDER_ENDPOINT.fullmatch(line)
            if not match:
                raise SourceInvalid("FULL_ENDPOINT_FORMAT_CHANGED")
            provider, model_id, context, endpoint_url = match.groups()
            endpoints.append({
                "provider": provider,
                "provider_model_id_claimed": model_id,
                "context_claimed": context,
                "provider_page_claimed": endpoint_url,
            })
    if not title or len(title) > 120 or not url or not MODEL_URL.fullmatch(url) or capabilities is None:
        raise SourceInvalid("FULL_MODEL_INCOMPLETE")
    if not endpoints:
        raise SourceInvalid("FULL_MODEL_NO_ENDPOINT")
    return {
        "name": title, "model_page": url, "developer": developer,
        "reasoning": "reasoning" in capabilities,
        "capabilities_claimed": capabilities,
        "aa_intelligence": aa, "gpqa_diamond": gpqa,
        "endpoints_claimed": endpoints,
    }


def parse_full_dump(raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_FULL_BYTES:
        raise SourceInvalid("FULL_SIZE_INVALID")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise SourceInvalid("FULL_ENCODING_INVALID") from exc
    if not lines or lines[0] != "# LLM Perks — full data dump":
        raise SourceInvalid("FULL_SOURCE_UNKNOWN")
    stamp = None
    section_seen = False
    done = False
    model_lines = []
    models = {}
    endpoint_count = 0
    total = None

    def accept(block):
        nonlocal endpoint_count
        model = _build_model(block)
        if model is not None:
            key = model["model_page"]
            if key in models:
                raise SourceInvalid("FULL_MODEL_DUPLICATE")
            models[key] = model
            endpoint_count += len(model["endpoints_claimed"])
            if len(models) > 1000 or endpoint_count > 4000:
                raise SourceInvalid("FULL_CATALOG_LIMIT_EXCEEDED")

    for line in lines[1:]:
        match = TIMESTAMP.fullmatch(line)
        if match:
            if stamp is not None:
                raise SourceInvalid("FULL_SNAPSHOT_DUPLICATE")
            stamp = match.group(1)
            _date(stamp)
        if line == "# ═══ Free models ═══":
            section_seen = True
            continue
        if not section_seen:
            continue
        if (match := TOTAL.fullmatch(line)):
            accept(model_lines)
            total = tuple(int(v) for v in match.groups())
            done = True
            break
        if line.startswith("## "):
            accept(model_lines)
            model_lines = [line]
        elif model_lines:
            model_lines.append(line)
    if not section_seen or not done or not stamp or not models or total is None:
        raise SourceInvalid("FULL_DATA_INCOMPLETE")
    # Footer online-provider count includes providers with no current model rows.
    if (total[0] != len(models) or total[1] != endpoint_count or
            not 1 <= total[2] <= 40):
        raise SourceInvalid("FULL_TOTAL_MISMATCH")
    result = {
        "schema": "llmperks-full-claims-v1", "source_url": FULL_URL,
        "publisher_snapshot": stamp, "models": models,
        "publisher_totals_not_verified": {"models": total[0], "endpoints": total[1],
                                          "providers": total[2]},
        "authority": "RESEARCH_ONLY_NO_EXECUTION_OR_BILLING",
    }
    result["sha256"] = fingerprint(result)
    return result


def fetch_full_dump(*, transport=None):
    """One fixed credential-free GET, bounded, no proxy/redirect inheritance."""
    if transport is None:
        class NoRedirect(request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        transport = request.build_opener(request.ProxyHandler({}), NoRedirect()).open
    req = request.Request(FULL_URL, method="GET", headers={
        "Accept": "text/plain", "User-Agent": "Foundation-Research/1"})
    try:
        with transport(req, timeout=12) as response:
            if getattr(response, "status", 200) != 200:
                raise SourceInvalid("FULL_HTTP_NOT_OK")
            raw = response.read(MAX_FULL_BYTES + 1)
    except (OSError, TimeoutError) as exc:
        raise SourceInvalid("FULL_SOURCE_UNAVAILABLE") from exc
    return parse_full_dump(raw)


def ranked_reasoning(catalog, *, metric="aa_intelligence", limit=25):
    """Exact descending score for explicitly tagged reasoning models only.

    Two independent ranking choices:
    - aa_intelligence: overall intelligence index (not reasoning-specific)
    - gpqa_diamond: graduate-level scientific question accuracy proxy
    """
    if catalog.get("schema") != "llmperks-full-claims-v1" or catalog.get("source_url") != FULL_URL:
        raise SourceInvalid("FULL_CATALOG_IDENTITY_INVALID")
    # Rankings must use the exact publisher snapshot parsed and fingerprinted at intake.
    # A modified cached catalog is research corruption, never an accepted ranking.
    if catalog.get("sha256") != fingerprint({k: v for k, v in catalog.items() if k != "sha256"}):
        raise SourceInvalid("FULL_CATALOG_FINGERPRINT_MISMATCH")
    if metric not in RANK_METRICS or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("INVALID_RANK_PARAMETERS")
    secondary = "gpqa_diamond" if metric == "aa_intelligence" else "aa_intelligence"
    candidates = [m for m in catalog["models"].values()
                  if m["reasoning"] and m[metric] is not None]
    candidates.sort(key=lambda m: (-m[metric], -(m[secondary] or 0), m["name"], m["model_page"]))
    return {
        "schema": "llmperks-score-ranked-research-v1",
        "metric": metric, "score_meaning": (
            "overall_intelligence_not_reasoning_only" if metric == "aa_intelligence"
            else "graduate_science_qa_proxy_not_general_reasoning"),
        "source_url": FULL_URL, "source_snapshot": catalog["publisher_snapshot"],
        "available_scored_reasoning_models": len(candidates),
        "missing_primary_score_excluded": sum(
            1 for m in catalog["models"].values() if m["reasoning"] and m[metric] is None),
        "ranked": [
            {"rank": rank, "name": m["name"], "model_page": m["model_page"],
             "aa_intelligence": m["aa_intelligence"], "gpqa_diamond": m["gpqa_diamond"],
             "providers": [e["provider"] for e in m["endpoints_claimed"]],
             "provider_model_ids_claimed": [
                 {"provider": e["provider"], "model_id": e["provider_model_id_claimed"]}
                 for e in m["endpoints_claimed"]],
             "provider_free_terms_verified": False,
             "account_no_auto_charge_verified": False,
             "execution_authorized": False}
            for rank, m in enumerate(candidates[:limit], 1)],
        "execution_authorized": False,
    }


def ranked_review_note(catalog, *, limit=10):
    """Short nonsecret Drive/KLM handoff, no account claims or side effects."""
    aa = ranked_reasoning(catalog, metric="aa_intelligence", limit=limit)
    gpqa = ranked_reasoning(catalog, metric="gpqa_diamond", limit=limit)
    lines = ["# LLMPerks reasoning performance observations — UNVERIFIED",
             "Snapshot: " + catalog["publisher_snapshot"],
             "Source: " + FULL_URL,
             "No account, payment, key, provider route or official pricing is verified.",
             "AA Index = overall intelligence. GPQA = scientific reasoning proxy.",
             "Only explicitly tagged reasoning models with published scores are ranked."]
    for heading, result in (("AA Index descending", aa), ("GPQA Diamond descending", gpqa)):
        lines.append("")
        lines.append("## " + heading)
        for m in result["ranked"]:
            lines.append("%d. %s | AA=%s | GPQA=%s%% | %s" % (
                m["rank"], m["name"], m["aa_intelligence"],
                m["gpqa_diamond"] if m["gpqa_diamond"] is not None else "unknown",
                m["model_page"]))
    lines.append("")
    lines.append("Manual provider selection and official no-auto-charge verification required.")
    return "\n".join(lines) + "\n"
