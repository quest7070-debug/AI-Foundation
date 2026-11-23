"""Free GitHub Issue fallback for LLMPerks audit when Actions artifacts are full.

Stores a source-only SHA-bound compressed *featured* snapshot in a dedicated
Issue body for next-run deltas. Ranks and service counts are readable Markdown;
no provider credentials, private data or API execution permits are stored.
Only the default-branch GitHub Actions job may modify that dedicated issue.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
import zlib

from .llmperks_discovery import SOURCE_URL, SourceInvalid

MARKER = re.compile(r"<!-- FOUNDATION_LLMPERKS_SNAPSHOT_V1:([A-Za-z0-9_-]{20,20000}):([a-f0-9]{64}) -->")
MAX_ISSUE_BODY = 60000
MAX_SNAPSHOT = 131072


def _serialized(snapshot):
    if (type(snapshot) is not dict
            or snapshot.get("schema") != "llmperks-curated-v1"
            or snapshot.get("source_url") != SOURCE_URL
            or type(snapshot.get("featured_model_pages")) is not dict
            or type(snapshot.get("provider_summaries")) is not dict
            or type(snapshot.get("publisher_snapshot")) is not str):
        raise SourceInvalid("ISSUE_SNAPSHOT_IDENTITY_UNVERIFIED")
    raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    if not 0 < len(raw) <= MAX_SNAPSHOT:
        raise SourceInvalid("ISSUE_SNAPSHOT_TOO_LARGE")
    return raw


def encode_snapshot(snapshot):
    raw = _serialized(snapshot)
    compressed = zlib.compress(raw, level=9)
    token = base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")
    return f"<!-- FOUNDATION_LLMPERKS_SNAPSHOT_V1:{token}:{hashlib.sha256(raw).hexdigest()} -->"


def decode_snapshot(body):
    """None means an empty newly provisioned Issue; corruption never becomes baseline."""
    if type(body) is not str:
        raise SourceInvalid("ISSUE_BODY_MISSING")
    match = MARKER.search(body)
    if match is None:
        if "FOUNDATION_LLMPERKS_SNAPSHOT_" in body:
            raise SourceInvalid("ISSUE_SNAPSHOT_MARKER_INVALID")
        return None
    token, expected = match.groups()
    try:
        packed = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        decomp = zlib.decompressobj()
        raw = decomp.decompress(packed, MAX_SNAPSHOT + 1)
        if len(raw) > MAX_SNAPSHOT or not decomp.eof or decomp.unused_data or decomp.unconsumed_tail:
            raise SourceInvalid("ISSUE_SNAPSHOT_DECOMPRESS_INVALID")
        if hashlib.sha256(raw).hexdigest() != expected:
            raise SourceInvalid("ISSUE_SNAPSHOT_DIGEST_MISMATCH")
        snapshot = json.loads(raw)
    except SourceInvalid:
        # SourceInvalid subclasses ValueError: preserve the precise failing
        # integrity check instead of relabelling tampering as a decode error.
        raise
    except (ValueError, UnicodeError, zlib.error) as exc:
        raise SourceInvalid("ISSUE_SNAPSHOT_DECODE_INVALID") from exc
    _serialized(snapshot)
    return snapshot


def _safe_cell(value):
    """Compact plain markdown cell; no untrusted HTML/links in the table."""
    s = str(value)[:128]
    return s.replace("|", "／").replace("<", "‹").replace(">", "›").replace("\n", " ")


def make_issue_body(snapshot, report, rankings, projection):
    _serialized(snapshot)
    if (type(report) is not dict or report.get("schema") != "llmperks-review-v1"
            or report.get("source_url") != SOURCE_URL
            or report.get("current_sha256") != snapshot.get("sha256")
            or type(rankings) is not dict
            or rankings.get("schema") != "llmperks-reasoning-rankings-v1"
            or type(projection) is not dict
            or projection.get("schema") != "foundation-service-model-research-projection-v1"
            or rankings.get("source_snapshot") != projection.get("publisher_snapshot")
            or rankings.get("execution_authorized") is not False
            or projection.get("execution_authorized") is not False):
        raise SourceInvalid("ISSUE_RESEARCH_OUTPUT_MISMATCH")
    lines = [
        "# LLMPerks｜公開データ調査（研究用・無課金API接続許可ではない）",
        "",
        "GitHub ActionsのArtifact容量上限を回避するため、このIssue本文に直近の"
        "公開ランキング要約と前回差分用スナップショットを保持する。",
        "情報源： https://llmperks.com/llms-full.txt / https://llmperks.com/llms.txt",
        "LLMPerksはAPI提供者ではなく比較サイト。料金、自動課金不可、実利用可能性は未検証。",
        "",
        "- Full publisher snapshot: " + projection["publisher_snapshot"],
        "- Featured publisher snapshot (separate, may be older): " + snapshot["publisher_snapshot"],
        "- Claimed model API routes: " + str(projection["provider_model_records"]),
        "- Existing API research service matches: " + str(projection["direct_api_research_routes"]),
        "- Native-adapter provider mentions (not connected): " + str(projection["existing_adapter_model_mentions"]),
        "- Existing non-API development-tool mentions: " + str(projection["non_api_service_observations"]),
        "- Unmatched provider route observations: " + str(projection["unmatched_provider_records"]),
        "- New featured pages since prior snapshot: " + str(len(report["new_featured"])),
        "- Removed from featured: " + str(len(report["no_longer_featured_NOT_RETIRED"]))
          + " (NOT a retired model signal)",
        "",
    ]
    for metric, title in (
        ("aa_intelligence", "AA Intelligence Index（総合性能）"),
        ("gpqa_diamond", "GPQA Diamond（高度科学推論代理指標）"),
    ):
        values = rankings.get(metric, {}).get("ranked", [])
        if type(values) is not list or not values:
            raise SourceInvalid("ISSUE_RANKING_MISSING")
        lines += ["## " + title, "", "| # | Model | AA | GPQA |", "|---:|---|---:|---:|"]
        for row in values[:10]:
            lines.append("| " + str(row["rank"]) + " | " +
                         _safe_cell(row["name"]) + " | " +
                         _safe_cell(row.get("aa_intelligence", "—")) + " | " +
                         _safe_cell(row.get("gpqa_diamond", "—")) + " |")
        lines.append("")
    lines += [
        "## 保留中の提供元（サービスを自動登録しない）",
        "",
        ", ".join(_safe_cell(slug) + " (" + str(len(rows)) + ")"
                  for slug, rows in projection["unmatched_provider_slugs"].items()),
        "",
        "実行ルートはすべて無効。導入の手動選定、公式の無課金条件、実測受入は別工程。",
        "",
        encode_snapshot(snapshot),
    ]
    body = "\n".join(lines) + "\n"
    if len(body.encode("utf-8")) > MAX_ISSUE_BODY:
        raise SourceInvalid("ISSUE_BODY_EXCEEDS_LIMIT")
    return body


def _atomic(path, content):
    """This helper writes only files at explicit working-tree output paths."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    import os
    import tempfile
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                      prefix=".llmperks-issue-", delete=False) as f:
        os.chmod(f.name, 0o600)
        f.write(content)
        name = f.name
    os.replace(name, path)


def main(argv=None):
    p = argparse.ArgumentParser(description="Bounded research snapshot in dedicated GitHub Issue")
    commands = p.add_subparsers(dest="op", required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--body", required=True)
    restore.add_argument("--snapshot", required=True)
    render = commands.add_parser("render")
    for item in ("snapshot", "report", "ranked", "service-routes", "body", "payload"):
        render.add_argument("--" + item, required=True)
    args = p.parse_args(argv)
    try:
        if args.op == "restore":
            previous = decode_snapshot(Path(args.body).read_text(encoding="utf-8"))
            if previous is not None:
                _atomic(args.snapshot, json.dumps(previous, ensure_ascii=False, indent=2) + "\n")
            print("ISSUE_PRIOR=" + ("RESTORED" if previous is not None else "BASELINE"))
        else:
            load = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
            body = make_issue_body(load(args.snapshot), load(args.report),
                                   load(args.ranked), load(args.service_routes))
            _atomic(args.body, body)
            _atomic(args.payload, json.dumps({"body": body}, ensure_ascii=False))
            print("ISSUE_RECORD_PREPARED")
        return 0
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        print("ISSUE_SNAPSHOT_UNVERIFIED:" + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
