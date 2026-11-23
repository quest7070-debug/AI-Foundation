"""Read-only three-agent mailbox verification for externally exported Muse reports.

Drive transports untrusted bytes. GPT suggestions and Muse reports never authorize
Foundation actions, Guard permits, Paseo tasks, billing, or automatic issues.
"""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlsplit

from ai_foundation.external_research_handoff import parse_external_research_handoff

_MAX_BYTES = 131_072
_GOOGLE_DOC_PATH = re.compile(r"^/document/d/([A-Za-z0-9_-]{12,})/(?:edit)?$")
_GOOGLE_RAW_PATH = re.compile(r"^/file/d/([A-Za-z0-9_-]{12,})/view$")


def _source_document(url: str, *, allow_drive_file: bool = False) -> str:
    """Validate a source locator, not its authenticity or permissions."""
    if not isinstance(url, str) or len(url) > 1024:
        raise ValueError("invalid source document URL")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https" or parsed.username is not None
        or parsed.password is not None or parsed.port not in (None, 443)
        or parsed.query or parsed.fragment
    ):
        raise ValueError("source must be a plain Google Docs URL")
    if parsed.hostname == "docs.google.com" and _GOOGLE_DOC_PATH.fullmatch(parsed.path):
        return "https://docs.google.com" + parsed.path
    if (allow_drive_file and parsed.hostname == "drive.google.com"
            and _GOOGLE_RAW_PATH.fullmatch(parsed.path)):
        return "https://drive.google.com" + parsed.path
    raise ValueError("source must be a plain Google Docs URL or explicitly allowed Drive file URL")


def validate_muse_mailbox_document(
    document_text: str, *, expected_correlation_id: str, source_document_url: str,
    allow_drive_file: bool = False,
) -> dict[str, object]:
    """Produce a non-authoritative, deterministic receipt after structural checks.

    The raw document must be JSON-only, with no markdown fences or preface.
    The original candidate is never rewritten or normalized silently.
    """
    if not isinstance(document_text, str) or len(document_text.encode("utf-8")) > _MAX_BYTES:
        raise ValueError("invalid mailbox document or size")
    if (
        not isinstance(expected_correlation_id, str)
        or not expected_correlation_id.strip()
        or len(expected_correlation_id) > 128
    ):
        raise ValueError("invalid expected correlation ID")
    source = _source_document(source_document_url, allow_drive_file=allow_drive_file)
    handoff = parse_external_research_handoff(document_text.strip())
    if handoff.correlation_id != expected_correlation_id:
        raise ValueError("correlation ID mismatch")
    # Canonical content digest comes from the strict source-only Muse adapter.
    key = hashlib.sha256(
        (expected_correlation_id + "\n" + handoff.content_sha256).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": 1,
        "type": "foundation_candidate_validation_receipt",
        "correlation_id": handoff.correlation_id,
        "source_document_url": source,
        "claimed_producer": handoff.claimed_producer,
        "candidate_sha256": handoff.content_sha256,
        "idempotency_key": key,
        "findings_count": len(handoff.result.evidence),
        "status": "STRUCTURALLY_VALID_UNVERIFIED",
        "review_required": True,
        "trusted_as_authority": False,
        "execution_authorized": False,
    }


def receipt_json(document_text: str, *, expected_correlation_id: str,
                 source_document_url: str) -> str:
    """Return stable, inspectable JSON; does not write or send to Google Drive."""
    receipt = validate_muse_mailbox_document(
        document_text,
        expected_correlation_id=expected_correlation_id,
        source_document_url=source_document_url,
    )
    return json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
