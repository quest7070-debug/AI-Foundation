"""Read-only preview for the seven-column Human Model Google Sheets export.

This module never imports rows into the ledger and never treats sheet text as
speaker authentication, consent, source identity, revision, valid time or authority.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

COLUMNS = (
    "category",
    "target",
    "provisional_understanding",
    "evidence_source_type",
    "certainty",
    "update_rule",
    "prohibition",
)

ALIASES = {
    "category": {"category", "カテゴリ", "区分"},
    "target": {"target", "対象", "ターゲット"},
    "provisional_understanding": {
        "provisional understanding", "provisional_understanding",
        "暫定的な理解", "暫定理解", "仮の理解",
    },
    "evidence_source_type": {
        "evidence source type", "evidence_source_type",
        "根拠ソース種別", "証拠ソース種別", "根拠の種類",
    },
    "certainty": {"certainty", "確実性", "確度"},
    "update_rule": {"update rule", "update_rule", "更新ルール", "更新条件"},
    "prohibition": {"prohibition", "禁止事項", "禁止"},
}

UNRESOLVED_PROVENANCE = (
    "immutable_source_record_id",
    "unambiguous_source_revision",
    "verified_speaker_attribution",
    "effective_valid_interval",
    "original_transcript_or_source_reference",
)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _header_key(value: str) -> str:
    return " ".join((value or "").strip().casefold().split())


def _resolve_headers(headers: Sequence[str], header_map: Mapping[str, str] | None = None) -> dict[str, int]:
    if not headers or not any(str(h).strip() for h in headers):
        raise ValueError("CSV header row is required")
    normalized = [_header_key(str(h)) for h in headers]
    if len(normalized) != len(set(normalized)):
        raise ValueError("duplicate source column headers")

    mapping = dict(header_map or {})
    unknown = set(mapping) - set(COLUMNS)
    if unknown:
        raise ValueError(f"unknown canonical header mapping: {sorted(unknown)}")

    result: dict[str, int] = {}
    for canonical in COLUMNS:
        if canonical in mapping:
            wanted = _header_key(mapping[canonical])
            positions = [i for i, item in enumerate(normalized) if item == wanted]
        else:
            accepted = {_header_key(item) for item in ALIASES[canonical]}
            positions = [i for i, item in enumerate(normalized) if item in accepted]
        if len(positions) != 1:
            raise ValueError(f"expected exactly one source column for {canonical}")
        result[canonical] = positions[0]
    if len(set(result.values())) != len(COLUMNS):
        raise ValueError('canonical columns must map to distinct source headers')
    return result


def preview_rows(
    *,
    sheet_id: str | int,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    header_map: Mapping[str, str] | None = None,
    export_sha256: str | None = None,
) -> dict:
    """Build an in-memory preview. No SQLite, Drive or network writes occur."""
    sheet = str(sheet_id).strip()
    if not sheet:
        raise ValueError("sheet_id is required")
    positions = _resolve_headers(headers, header_map)
    raw_headers = [str(header) for header in headers]

    prepared = []
    for row_number, supplied in enumerate(rows, start=2):
        values = [str(value) for value in supplied]
        if not any(value.strip() for value in values):
            continue
        digest_input = {"headers": raw_headers, "values": values}
        content_digest = _sha256(_canonical(digest_input).encode("utf-8"))
        canonical_values = {
            field: (values[index] if index < len(values) else "")
            for field, index in positions.items()
        }
        shape_matches = len(values) == len(raw_headers)
        prepared.append({
            "row_number": row_number,
            "values": values,
            "content_sha256": content_digest,
            "preview_key": _sha256(f"sheet:{sheet}\0{content_digest}".encode("utf-8")),
            "canonical_values": canonical_values,
            "row_shape_matches_header": shape_matches,
            "extra_values": values[len(raw_headers):] if len(values) > len(raw_headers) else [],
            "missing_header_values": max(0, len(raw_headers) - len(values)),
        })

    duplicate_counts = Counter(item["content_sha256"] for item in prepared)
    output_rows = []
    for item in prepared:
        unresolved = list(UNRESOLVED_PROVENANCE)
        if not item["row_shape_matches_header"]:
            unresolved.append("source_row_shape")
        duplicate = duplicate_counts[item["content_sha256"]] > 1
        output_rows.append({
            "preview_key": item["preview_key"],
            "row_anchor": {"sheet_id": sheet, "export_row_number": item["row_number"]},
            "row_anchor_limit": "CSV export position only; not a verified immutable or round-tripped Drive row identity",
            "content_sha256": item["content_sha256"],
            "identity_state": "ambiguous_duplicate_content" if duplicate else "no_immutable_source_record_id",
            "row_shape_matches_header": item["row_shape_matches_header"],
            "missing_header_values": item["missing_header_values"],
            "extra_values": item["extra_values"],
            "raw_cells": [
                {"column": header, "value": item["values"][index] if index < len(item["values"]) else None}
                for index, header in enumerate(raw_headers)
            ],
            "fields": item["canonical_values"],
            "field_semantics": {
                "provisional_understanding": "unverified_summary_or_interpretation",
                "evidence_source_type": "source_claim_not_independently_verified",
                "certainty": "preserved_as_source_text_not_numeric_confidence",
                "update_rule": "preserved_as_source_text_not_applied",
                "prohibition": "preserved_as_source_text_not_policy_authority",
            },
            "provenance": {
                "source_sheet_id": sheet,
                "source_row_anchor": f"export-row:{item['row_number']}",
                "source_revision": None,
                "speaker_attribution": "unverified",
                "effective_valid_from": None,
                "effective_valid_to": None,
                "original_source_reference": None,
                "unresolved": unresolved,
            },
            "imported": False,
            "authority_granted": False,
            "requires_human_review": True,
        })

    return {
        "format": "human-model-drive-source-preview/1",
        "mode": "read_only_preview",
        "source": {"provider": "google_sheets_export", "sheet_id": sheet, "export_sha256": export_sha256},
        "schema": {"canonical_columns": list(COLUMNS), "source_headers": raw_headers},
        "row_count": len(output_rows),
        "duplicate_content_groups": sum(1 for count in duplicate_counts.values() if count > 1),
        "rows": output_rows,
        "imported": False,
        "ledger_mutations": 0,
        "llm_calls": 0,
        "authority_granted": False,
        "warning": "This report preserves exported cell values but cannot prove source identity, speaker, revision, valid time, consent or original-transcript fidelity.",
    }


def preview_csv(
    path: str | Path,
    *,
    sheet_id: str | int,
    delimiter: str = ",",
    header_map: Mapping[str, str] | None = None,
) -> dict:
    """Read a UTF-8/UTF-8-BOM CSV/TSV export and return a non-persistent preview."""
    if delimiter not in {",", "\t", ";"}:
        raise ValueError("delimiter must be comma, tab or semicolon")
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("export must be UTF-8 or UTF-8 with BOM") from exc
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        headers = next(reader)
    except StopIteration as exc:
        raise ValueError("empty export") from exc
    return preview_rows(
        sheet_id=sheet_id,
        headers=headers,
        rows=list(reader),
        header_map=header_map,
        export_sha256=_sha256(raw),
    )


def main(argv=None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Create a read-only preview of the Human Model Sheets export.")
    parser.add_argument("--csv", type=Path, required=True, help="UTF-8 CSV export; original file is never modified")
    parser.add_argument("--sheet-id", required=True, help="Google Sheets tab sheetId (for example: 108)")
    parser.add_argument("--delimiter", choices=[",", "tab", ";"], default=",")
    parser.add_argument("--header-map-json", type=Path, help="Optional JSON object mapping canonical names to exact source headers")
    parser.add_argument("--output", type=Path, help="Optional local JSON report path; defaults to stdout")
    args = parser.parse_args(argv)
    try:
        header_map = json.loads(args.header_map_json.read_text(encoding="utf-8")) if args.header_map_json else None
        if header_map is not None and not isinstance(header_map, dict):
            raise ValueError("header map must be a JSON object")
        result = preview_csv(
            args.csv,
            sheet_id=args.sheet_id,
            delimiter={"tab": "\t"}.get(args.delimiter, args.delimiter),
            header_map=header_map,
        )
        rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            same_export = args.output.resolve() == args.csv.resolve()
            if args.output.exists():
                same_export = same_export or os.path.samefile(args.output, args.csv)
            if same_export:
                raise ValueError('preview output must not overwrite the source export')
            args.output.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    descriptor = -1
                    stream.write(rendered)
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
        else:
            sys.stdout.write(rendered)
        return 0
    except (OSError, UnicodeError, csv.Error, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=False) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
