"""Approved HumanModel dispute evidence must not be silently declared exhaustive.

No private ledger, actual model call, native effects, or unsafe unapproved scope.
"""
import json
import unittest
from ai_foundation.core import Decision
from ai_foundation.human_model_context import HumanModelContext, HumanModelBinding


class Allow:
    def preflight(self, *args):
        return Decision.ALLOW


def record(identity, disputed):
    return {
        "id": identity, "kind": "decision", "scope": "career",
        "content": "synthetic " + identity,
        "source_uri": "synthetic:" + identity,
        "source_revision": "1", "observed_at": None,
        "privacy": "private", "disputed": int(disputed),
        "content_sha256": "0" * 64,
    }


def snapshot():
    return {
        "view_id": "v", "scope": "career", "view_revision": 1,
        "records": [record("undisputed", False), record("disputed", True)],
        "truncated": False, "omitted_record_ids": [], "next_offset": None,
        "snapshot_sha256": "a"*64,
    }


def context(index):
    return HumanModelContext(
        HumanModelBinding("owner", "/synthetic/external-ledger", "v", ("career",), "private"),
        lambda *a, **k: snapshot(), guard=Allow(), run_id="test",
        search_backend=index)


class ConflictCoverageTests(unittest.TestCase):
    def search(self, index):
        return json.loads(context(index).search("owner", "career", "criterion"))

    def test_ranked_match_warns_of_omitted_disputed_original(self):
        answer = self.search(lambda src, query: {"records": src["records"][:1]})
        self.assertEqual(answer["status"], "AVAILABLE")
        self.assertEqual([r["id"] for r in answer["records"]], ["undisputed"])
        self.assertEqual(answer["retrieval_coverage"]["approved_source_count"], 2)
        self.assertEqual(answer["retrieval_coverage"]["returned_source_count"], 1)
        self.assertEqual(answer["retrieval_coverage"]["unreturned_disputed_count"], 1)
        self.assertFalse(answer["retrieval_coverage"]["exhaustive_for_approved_view"])
        self.assertEqual(answer["retrieval_coverage"]["conflict_adjudication"], "NOT_PERFORMED")
        self.assertFalse(answer["execution_authority"])

    def test_no_match_does_not_claim_no_disputed_evidence(self):
        answer = self.search(lambda src, query: {"records": []})
        self.assertEqual(answer["status"], "NO_MATCH")
        self.assertEqual(answer["retrieval_coverage"]["approved_source_count"], 2)
        self.assertEqual(answer["retrieval_coverage"]["unreturned_disputed_count"], 1)
        self.assertFalse(answer["retrieval_coverage"]["exhaustive_for_approved_view"])

    def test_all_returned_still_does_not_claim_conflict_adjudication(self):
        answer = self.search(lambda src, query: {"records": src["records"]})
        self.assertEqual(answer["retrieval_coverage"]["approved_source_count"], 2)
        self.assertEqual(answer["retrieval_coverage"]["returned_source_count"], 2)
        self.assertEqual(answer["retrieval_coverage"]["unreturned_disputed_count"], 0)
        self.assertTrue(answer["retrieval_coverage"]["exhaustive_for_approved_view"])
        self.assertEqual(answer["retrieval_coverage"]["conflict_adjudication"], "NOT_PERFORMED")

    def test_indexed_disputed_record_is_not_counted_as_omitted(self):
        answer = self.search(lambda src, query: {"records": src["records"][1:]})
        self.assertEqual([r["id"] for r in answer["records"]], ["disputed"])
        self.assertEqual(answer["retrieval_coverage"]["unreturned_disputed_count"], 0)
        self.assertFalse(answer["retrieval_coverage"]["exhaustive_for_approved_view"])

    def test_search_does_not_trust_backend_forged_coverage(self):
        def forge(src, query):
            return {"records": src["records"][:1], "retrieval_coverage": {
                "exhaustive_for_approved_view": True,
                "unreturned_disputed_count": 0,
                "conflict_adjudication": "RESOLVED",
            }}
        answer = self.search(forge)
        self.assertEqual(answer["retrieval_coverage"]["unreturned_disputed_count"], 1)
        self.assertFalse(answer["retrieval_coverage"]["exhaustive_for_approved_view"])
        self.assertEqual(answer["retrieval_coverage"]["conflict_adjudication"], "NOT_PERFORMED")

    def test_unauthorized_scope_does_not_return_coverage_or_private_counts(self):
        result = json.loads(context(lambda src, query: {"records": src["records"]}).search(
            "owner", "other", "criterion"))
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertNotIn("retrieval_coverage", result)


if __name__ == "__main__":
    unittest.main()
