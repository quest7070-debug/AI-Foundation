"""Cross-page view revision cannot silently change within one HumanModel request.

This test is standalone: synthetic source only, no private ledger, model or
Cognee execution.
"""
import hashlib
import json
import unittest

from ai_foundation.core import Decision
from ai_foundation.human_model_context import HumanModelBinding, HumanModelContext


class AllowGuard:
    def preflight(self, plan, canon):
        return Decision.ALLOW


def page(revision, offset, scope="career", next_offset=None):
    row = {
        "id": f"record-{scope}-{offset}-{revision}",
        "kind": "decision", "scope": scope,
        "content": "synthetic claim, not private evidence",
        "source_uri": "synthetic:test", "source_revision": str(revision),
        "observed_at": None, "privacy": "private", "disputed": 0,
    }
    row["content_sha256"] = hashlib.sha256(row["content"].encode()).hexdigest()
    result = {
        "view_id": "v", "scope": scope, "view_revision": revision,
        "records": [row], "truncated": next_offset is not None,
        "omitted_record_ids": [], "next_offset": next_offset,
    }
    result["snapshot_sha256"] = hashlib.sha256(
        json.dumps(result, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return result


class VersionedReader:
    def __init__(self):
        self.revisions = {"career": 7, "creative": 13}
        self.calls = []

    def __call__(self, root, *, view_id, scope, max_privacy, max_records, max_bytes, offset):
        self.calls.append((scope, offset))
        return page(self.revisions[scope], offset, scope, 32 if offset == 0 else None)


class PinnedPaginationTests(unittest.TestCase):
    def setUp(self):
        self.reader = VersionedReader()
        self.context = HumanModelContext(
            HumanModelBinding("owner", "/synthetic/external-ledger", "v",
                              ("career", "creative"), "private"),
            self.reader, guard=AllowGuard(), run_id="test")

    def get(self, scope="career", offset=0):
        return json.loads(self.context.read("owner", scope, offset=offset))

    def test_changed_view_revision_is_rejected_before_serving_page_two(self):
        first = self.get()
        self.assertEqual(first["status"], "PARTIAL")
        self.reader.revisions["career"] = 8
        second = self.get(offset=first["next_offset"])
        self.assertEqual(second["status"], "UNAVAILABLE")
        self.assertEqual(second["reason"], "VIEW_REVISION_CHANGED_DURING_PAGINATION")
        self.assertNotIn("records", second)
        self.assertEqual(len(self.context.receipts), 1)

    def test_unchanged_view_revision_allows_page_two(self):
        first = self.get()
        second = self.get(offset=first["next_offset"])
        self.assertEqual(second["status"], "AVAILABLE")
        self.assertEqual(second["view_revision"], first["view_revision"])
        self.assertNotEqual(second["records"], first["records"])
        self.assertEqual(len(self.context.receipts), 2)

    def test_direct_second_page_without_revision_anchor_is_refused(self):
        result = self.get(offset=32)
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["reason"], "PAGE_REVISION_NOT_PINNED")
        self.assertEqual(self.reader.calls, [])

    def test_skipped_offset_is_not_treated_as_the_same_revision_chain(self):
        self.get()
        result = self.get(offset=64)
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["reason"], "PAGE_SEQUENCE_INVALID")
        self.assertEqual(self.reader.calls, [("career", 0)])

    def test_reopen_page_zero_starts_new_revision_session(self):
        first = self.get()
        self.reader.revisions["career"] = 8
        new_first = self.get()
        self.assertEqual(new_first["status"], "PARTIAL")
        self.assertNotEqual(new_first["view_revision"], first["view_revision"])
        second = self.get(offset=new_first["next_offset"])
        self.assertEqual(second["status"], "AVAILABLE")
        self.assertEqual(second["view_revision"], 8)

    def test_failed_new_first_page_invalidates_previous_anchor(self):
        first = self.get()
        original = self.context._reader

        def unavailable(*args, **kwargs):
            raise FileNotFoundError("synthetic source missing")

        self.context._reader = unavailable
        self.assertEqual(self.get()["status"], "UNAVAILABLE")
        self.context._reader = original
        self.assertEqual(self.get(offset=first["next_offset"])["reason"],
                         "PAGE_REVISION_NOT_PINNED")

    def test_failed_continuation_invalidates_previous_anchor(self):
        first = self.get()
        original = self.context._reader

        def invalid(*args, **kwargs):
            raise ValueError("synthetic source drift")

        self.context._reader = invalid
        self.assertEqual(self.get(offset=first["next_offset"])["status"], "UNAVAILABLE")
        self.context._reader = original
        self.assertEqual(self.get(offset=first["next_offset"])["reason"],
                         "PAGE_REVISION_NOT_PINNED")

    def test_scope_anchors_remain_independent(self):
        first_career = self.get("career")
        first_creative = self.get("creative")
        self.reader.revisions["career"] = 9
        self.assertEqual(self.get("creative", first_creative["next_offset"])["status"],
                         "AVAILABLE")
        self.assertEqual(self.get("career", first_career["next_offset"])["status"],
                         "UNAVAILABLE")

    def test_malformed_next_offset_does_not_create_an_unbound_cursor(self):
        original = self.reader

        def invalid(*args, **kwargs):
            return page(7, kwargs["offset"], kwargs["scope"],
                        kwargs["offset"] if kwargs["offset"] == 0 else 32)

        self.context._reader = invalid
        bad = self.get()
        self.assertEqual(bad["status"], "UNAVAILABLE")
        self.assertEqual(bad["reason"], "APPROVED_CURRENT_VIEW_UNAVAILABLE")
        self.context._reader = original
        self.assertEqual(self.get(offset=32)["reason"], "PAGE_REVISION_NOT_PINNED")


if __name__ == "__main__":
    unittest.main()
