"""LLMPerks public index ingestion. Research evidence only, never route admission.

The public llms.txt is a curated featured list, NOT all free model endpoints.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
from urllib import request
from urllib.parse import urlsplit

SOURCE_URL = "https://llmperks.com/llms.txt"
MAX_BYTES = 131072
ENTRY = re.compile(r"^- \[([^\]\r\n]{1,120})\]\((https://(?:www\.)?llmperks\.com/[a-z0-9-]+(?:/[a-z0-9-]+)?)\): ([^\r\n]{1,1000})$")
DATE = re.compile(r"^Snapshot: (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z)$")
COUNTS = re.compile(r"^Free models: (\d+) \((\d+) endpoints\) .+Providers online: (\d+)/(\d+)$")
SERVICE_ID_HINTS = {"groq":"groq", "openrouter":"openrouter", "gemini":"gemini-api",
                    "opencode":"opencode-zen-free", "nvidia":"nvidia", "cloudflare":"cloudflare",
                    "huggingface":"huggingface-inference-providers", "cohere":"cohere",
                    "cerebras":"cerebras"}


class SourceInvalid(ValueError):
    pass


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                  separators=(",", ":")).encode("utf-8")).hexdigest()


def parse_index(raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES:
        raise SourceInvalid("INVALID_SIZE")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise SourceInvalid("INVALID_ENCODING") from exc
    if not lines or lines[0] != "# LLM Perks":
        raise SourceInvalid("UNEXPECTED_SOURCE")
    section = ""
    stamp = counts = None
    models, providers = {}, {}
    for line in lines:
        if line.startswith("## "):
            section = line[3:]
            continue
        if (m := DATE.fullmatch(line)):
            stamp = m.group(1)
            try:
                datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError as exc:
                raise SourceInvalid("INVALID_DATE") from exc
            continue
        if (m := COUNTS.fullmatch(line)):
            counts = {"published_models": int(m.group(1)), "published_endpoints": int(m.group(2)),
                      "providers_online": int(m.group(3)), "providers_total": int(m.group(4))}
            continue
        if section not in ("Best free models right now", "Providers") or not line.startswith("- "):
            continue
        m = ENTRY.fullmatch(line)
        if not m:
            raise SourceInvalid("INDEX_SHAPE_CHANGED")
        name, url, detail = m.groups()
        parts = urlsplit(url).path.strip("/").split("/")
        if section == "Best free models right now":
            if len(parts) != 2 or "free at " not in detail or url in models:
                raise SourceInvalid("INVALID_MODEL_ROW")
            slugs = detail.rsplit("free at ", 1)[1].split(", ")
            if any(not re.fullmatch(r"[a-z][a-z0-9-]{0,40}", slug) for slug in slugs):
                raise SourceInvalid("INVALID_SUPPLIER_SLUG")
            models[url] = {"name": name, "source_page": url, "free_at_claimed": sorted(set(slugs))}
            if len(models) > 80:
                raise SourceInvalid("MODEL_INDEX_TOO_LARGE")
        else:
            if len(parts) != 1 or parts[0] in providers:
                raise SourceInvalid("INVALID_PROVIDER_ROW")
            providers[parts[0]] = {"name": name, "source_page": url,
                                    "source_terms_excerpt": detail[:500],
                                    "existing_service_id_hint": SERVICE_ID_HINTS.get(parts[0])}
            if len(providers) > 40:
                raise SourceInvalid("PROVIDER_INDEX_TOO_LARGE")
    if not stamp or not counts or not models or not providers:
        raise SourceInvalid("INCOMPLETE_SOURCE")
    if counts["published_models"] < len(models) or counts["providers_online"] > counts["providers_total"]:
        raise SourceInvalid("INVALID_PUBLISHER_COUNTS")
    result = {"schema": "llmperks-curated-v1", "source_url": SOURCE_URL,
              "publisher_snapshot": stamp, "publisher_counts_unverified": counts,
              "featured_model_pages": models, "provider_summaries": providers,
              "coverage": "FEATURED_ONLY_NOT_FULL_CATALOG",
              "authority": "RESEARCH_ONLY_NO_EXECUTION_OR_BILLING"}
    result["sha256"] = fingerprint(result)
    return result


def fetch_index(*, transport=None):
    """One fixed public HTTPS GET. No provider calls, keys, proxy, or redirect."""
    if transport is None:
        class NoRedirect(request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        transport = request.build_opener(request.ProxyHandler({}), NoRedirect()).open
    req = request.Request(SOURCE_URL, method="GET",
                          headers={"Accept": "text/plain", "User-Agent": "Foundation-Research/1"})
    try:
        with transport(req, timeout=12) as response:
            if getattr(response, "status", 200) != 200:
                raise SourceInvalid("HTTP_NOT_OK")
            raw = response.read(MAX_BYTES + 1)
    except (OSError, TimeoutError) as exc:
        raise SourceInvalid("SOURCE_UNAVAILABLE") from exc
    return parse_index(raw)


def _verified_snapshot(snapshot, *, label):
    """Reject corrupt local snapshots before using their contents as delta evidence."""
    if (type(snapshot) is not dict or snapshot.get("schema") != "llmperks-curated-v1"
            or snapshot.get("source_url") != SOURCE_URL
            or type(snapshot.get("sha256")) is not str):
        raise SourceInvalid("INVALID_" + label)
    unsigned = {key: value for key, value in snapshot.items() if key != "sha256"}
    try:
        valid = fingerprint(unsigned) == snapshot["sha256"]
    except (TypeError, ValueError, OverflowError):
        valid = False
    if not valid:
        raise SourceInvalid("INVALID_" + label)
    for key in ("featured_model_pages", "provider_summaries"):
        if type(snapshot.get(key)) is not dict:
            raise SourceInvalid("INVALID_" + label)


def compare(current, previous=None):
    _verified_snapshot(current, label="CURRENT")
    if previous is not None:
        _verified_snapshot(previous, label="PREVIOUS")
    newer = current["featured_model_pages"]
    older = previous["featured_model_pages"] if previous else {}
    providers = current["provider_summaries"]
    old_providers = previous["provider_summaries"] if previous else {}
    return {
        "schema": "llmperks-review-v1", "source_url": SOURCE_URL,
        "publisher_snapshot": current["publisher_snapshot"],
        "baseline_only": previous is None,
        "new_featured": sorted(set(newer) - set(older)) if previous else [],
        "no_longer_featured_NOT_RETIRED": sorted(set(older) - set(newer)),
        "new_provider_summaries": sorted(set(providers) - set(old_providers)) if previous else [],
        "changed_provider_summaries": sorted(k for k in set(providers) & set(old_providers)
             if providers[k]["source_terms_excerpt"] != old_providers[k]["source_terms_excerpt"]),
        "no_longer_listed_NOT_RETIRED": sorted(set(old_providers) - set(providers)),
        "current_sha256": current["sha256"],
        "previous_sha256": previous["sha256"] if previous else None,
        "official_terms_reverification_required": True,
        "manual_provider_selection": True, "execution_authorized": False,
    }


def review_note(current, report):
    """Nonsecret plain-text handoff for existing owner-authorized Drive writer."""
    lines = ["# LLMPerks candidate observations (unverified)",
             "Source: " + SOURCE_URL,
             "Publisher snapshot: " + current["publisher_snapshot"],
             "Scope: featured model pages and provider summaries only.",
             "This is not all model IDs, API availability, or no-charge proof.",
             "Baseline only: " + str(report["baseline_only"]),
             "New featured: " + str(len(report["new_featured"])),
             "No longer featured (NOT retired): " + str(len(report["no_longer_featured_NOT_RETIRED"])),
             "Changed provider summaries: " + str(len(report["changed_provider_summaries"])),
             "Official provider terms and manual selection required."]
    for key in ("new_featured", "new_provider_summaries", "changed_provider_summaries"):
        lines.extend("- " + key + ": " + item for item in report[key])
    return "\n".join(lines) + "\n"
