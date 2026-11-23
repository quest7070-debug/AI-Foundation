import csv
import tempfile
import unittest
from pathlib import Path

from drive_sheet_preview import preview_csv, preview_rows


HEADERS = [
    "category", "target", "provisional understanding",
    "evidence source type", "certainty", "update rule", "prohibition",
]


class DriveSheetPreviewTests(unittest.TestCase):
    def test_preview_is_content_addressed_read_only_and_row_order_independent(self):
        rows = [
            ["goal", "work", "  draft value  ", "conversation summary", "medium", "review later", "not authority"],
            ["goal", "life", "another draft", "document", "low", "ask first", "no auto action"],
        ]
        first = preview_rows(sheet_id=108, headers=HEADERS, rows=rows)
        moved = preview_rows(sheet_id=108, headers=HEADERS, rows=list(reversed(rows)))
        left = {r["fields"]["target"]: r for r in first["rows"]}
        right = {r["fields"]["target"]: r for r in moved["rows"]}
        self.assertEqual(left["work"]["preview_key"], right["work"]["preview_key"])
        self.assertEqual(left["work"]["identity_state"], "no_immutable_source_record_id")
        self.assertFalse(first["imported"])
        self.assertEqual(first["ledger_mutations"], 0)
        self.assertEqual(left["work"]["raw_cells"][2]["value"], "  draft value  ")
        self.assertEqual(left["work"]["fields"]["prohibition"], "not authority")

    def test_preview_marks_duplicate_rows_as_ambiguous_not_distinct_identity(self):
        row = ["goal", "work", "same", "summary", "unknown", "manual", "no inference"]
        result = preview_rows(sheet_id="108", headers=HEADERS, rows=[row, row])
        self.assertEqual(result["duplicate_content_groups"], 1)
        self.assertEqual({r["identity_state"] for r in result["rows"]}, {"ambiguous_duplicate_content"})
        self.assertEqual(result["rows"][0]["preview_key"], result["rows"][1]["preview_key"])

    def test_csv_export_keeps_exact_cells_and_reports_export_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "human-model.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(HEADERS)
                writer.writerow(["goal", "work", "source text", "summary", "medium", "manual", "no automatic import"])
            result = preview_csv(path, sheet_id=108)
        self.assertEqual(len(result["source"]["export_sha256"]), 64)
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(result["rows"][0]["fields"]["target"], "work")

    def test_unrecognized_or_ambiguous_headers_fail_instead_of_guessing(self):
        with self.assertRaisesRegex(ValueError, "source column"):
            preview_rows(sheet_id=108, headers=["a", "b", "c", "d", "e", "f", "g"], rows=[[""] * 7])

    def test_row_shape_mismatch_and_missing_provenance_stay_explicit(self):
        row = ["goal", "work", "draft", "summary", "medium", "manual", "no auto", "unexpected"]
        result = preview_rows(sheet_id=108, headers=HEADERS, rows=[row])
        item = result["rows"][0]
        self.assertFalse(item["row_shape_matches_header"])
        self.assertEqual(item["extra_values"], ["unexpected"])
        self.assertIn("source_row_shape", item["provenance"]["unresolved"])
        self.assertEqual(item["provenance"]["speaker_attribution"], "unverified")
        self.assertFalse(item["imported"])


if __name__ == "__main__":
    unittest.main()
