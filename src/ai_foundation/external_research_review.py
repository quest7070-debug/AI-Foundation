"""Inert, per-finding review records for untrusted external research.

Review records never grant execution authority or mutate source receipts.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
import stat
from pathlib import Path

from ai_foundation.external_research_handoff import ExternalResearchHandoff

_DECISIONS = frozenset({"CANDIDATE", "HOLD", "REJECT"})


def build_review_record(
    handoff: ExternalResearchHandoff, decisions: list[dict[str, object]],
    *, reviewed_at: str, reviewer: str,
) -> dict[str, object]:
    """Require an explicit decision and rationale for every original finding."""
    stamp = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("reviewed_at requires timezone")
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 128:
        raise ValueError("invalid reviewer")
    evidence = handoff.result.evidence
    if not isinstance(decisions, list) or len(decisions) != len(evidence):
        raise ValueError("one decision required per finding")
    entries = []
    for index, (item, source) in enumerate(zip(decisions, evidence, strict=True)):
        if not isinstance(item, dict) or set(item) != {"decision", "rationale"}:
            raise ValueError("invalid review item")
        decision, rationale = item["decision"], item["rationale"]
        if not isinstance(decision, str) or decision not in _DECISIONS:
            raise ValueError("invalid decision")
        if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 2048:
            raise ValueError("invalid rationale")
        entries.append({
            "index": index,
            "decision": decision,
            "rationale": rationale,
            "source_url": source.source,
            "claim_sha256": hashlib.sha256(source.claim.encode("utf-8")).hexdigest(),
        })
    return {
        "schema_version": 1,
        "type": "external_research_finding_review",
        "correlation_id": handoff.correlation_id,
        "candidate_sha256": handoff.content_sha256,
        "reviewed_at": reviewed_at,
        "reviewer": reviewer,
        "findings": entries,
        "execution_authorized": False,
        "trusted_as_authority": False,
    }


def persist_review_record(path: Path, record: dict[str, object]) -> bool:
    """Create once; same bytes are idempotent, conflicting reviews fail closed."""
    if record.get("type") != "external_research_finding_review":
        raise ValueError("not a review record")
    if record.get("execution_authorized") is not False or record.get("trusted_as_authority") is not False:
        raise ValueError("review must not grant authority")
    payload = (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # The default pathlib mode is affected by umask and can create a
        # world-readable file containing owner review notes and source URLs.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600)
    except FileExistsError:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as source:
                info = os.fstat(source.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_nlink != 1 or info.st_mode & 0o077):
                    raise ValueError("untrusted existing review")
                if source.read(len(payload) + 1) == payload:
                    return False
        except OSError:
            raise ValueError("untrusted existing review") from None
        raise ValueError("conflicting existing review") from None
    with os.fdopen(fd, "wb") as output:
        output.write(payload)
    return True
