"""Strict, non-authoritative JSON handoff from independent research agents.

This module does not call Muse, grant tool authority, schedule work, or execute actions.
The producer field is an unverified claim, not an authentication assertion.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from urllib.parse import urlsplit

from ai_foundation.research import Evidence, ResearchResult

_MAX_BYTES = 131_072
_MAX_FINDINGS = 20
_ALLOWED_KEYS = frozenset({
    "schema_version", "producer", "correlation_id", "query",
    "generated_at", "findings", "uncertainty",
})
_FINDING_KEYS = frozenset({
    "source_url", "claim", "excerpt", "confidence",
    "observed_at", "published_at",
})
_CONFIDENCE = frozenset({"unknown", "low", "medium", "high"})


@dataclass(frozen=True)
class ExternalResearchHandoff:
    """Inert candidate evidence: never a reviewed task or execution contract."""

    correlation_id: str
    claimed_producer: str
    generated_at: str
    query: str
    content_sha256: str
    result: ResearchResult
    review_required: bool = True


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _object(value: object, keys: frozenset[str], name: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) - keys:
        raise ValueError(f"invalid {name} shape")
    return value


def _text(value: object, name: str, *, maximum: int, optional: bool = False) -> str:
    if value is None and optional:
        return ""
    if not isinstance(value, str) or len(value) > maximum or (not optional and not value.strip()):
        raise ValueError(f"invalid {name}")
    return value


def _timestamp(value: object, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    stamp = _text(value, name, maximum=64)
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid {name}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} requires timezone")
    return stamp


def _https_url(value: object) -> str:
    url = _text(value, "source_url", maximum=2048)
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or any(char.isspace() for char in url)
    ):
        raise ValueError("source_url must be an HTTPS reference")
    return url


def parse_external_research_handoff(payload: str) -> ExternalResearchHandoff:
    """Validate an untrusted report; preserve evidence without granting authority.

    Only accepts observations and explicit uncertainty. It cannot represent a
    proposed command, GitHub ready label, execution target, approval, or budget.
    """
    if not isinstance(payload, str) or len(payload.encode("utf-8")) > _MAX_BYTES:
        raise ValueError("handoff too large or not text")
    try:
        # Native Google Docs text exports may prepend one UTF-8 BOM. Strip only
        # that transport marker; duplicate keys and all other JSON bytes stay strict.
        raw = json.loads(payload.removeprefix("\ufeff"), object_pairs_hook=_unique_pairs)
    except (ValueError, TypeError) as error:
        raise ValueError("invalid handoff JSON") from error
    obj = _object(raw, _ALLOWED_KEYS, "handoff")
    if type(obj.get("schema_version")) is not int or obj["schema_version"] != 1:
        raise ValueError("unsupported schema_version")
    producer = _text(obj.get("producer"), "producer", maximum=64)
    if producer != "muse":
        raise ValueError("unexpected producer")
    correlation_id = _text(obj.get("correlation_id"), "correlation_id", maximum=128)
    query = _text(obj.get("query"), "query", maximum=2048)
    generated_at = _timestamp(obj.get("generated_at"), "generated_at")
    uncertainty = _text(obj.get("uncertainty", ""), "uncertainty", maximum=4096, optional=True)
    findings = obj.get("findings")
    if not isinstance(findings, list) or not 1 <= len(findings) <= _MAX_FINDINGS:
        raise ValueError("invalid findings")
    evidence = []
    for index, item in enumerate(findings):
        finding = _object(item, _FINDING_KEYS, f"finding[{index}]")
        source = _https_url(finding.get("source_url"))
        claim = _text(finding.get("claim"), "claim", maximum=4096)
        excerpt = _text(finding.get("excerpt", ""), "excerpt", maximum=4096, optional=True)
        confidence = _text(finding.get("confidence", "unknown"), "confidence", maximum=16)
        if confidence not in _CONFIDENCE:
            raise ValueError("invalid confidence")
        observed_at = _timestamp(finding.get("observed_at"), "observed_at", optional=True)
        published_at = _timestamp(finding.get("published_at"), "published_at", optional=True)
        evidence.append(Evidence(
            source=source, claim=claim, excerpt=excerpt, confidence=confidence,
            trusted_as_authority=False, observed_at=observed_at, published_at=published_at,
        ))
    canonical = json.dumps(raw, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return ExternalResearchHandoff(
        correlation_id=correlation_id,
        claimed_producer=producer,
        generated_at=generated_at,
        query=query,
        content_sha256=digest,
        result=ResearchResult(answer="", evidence=tuple(evidence), uncertainty=uncertainty),
    )
