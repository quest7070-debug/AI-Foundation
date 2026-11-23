"""Synthetic evidence tests for hypothesis evaluation."""
import unittest
from hypothesis_engine import evaluate_hypothesis

ROWS = [
    {"id": "s1", "scope": "work", "disputed": 0},
    {"id": "c1", "scope": "work", "disputed": 0},
    {"id": "other", "scope": "personal", "disputed": 0},
    {"id": "disputed", "scope": "work", "disputed": 1},
]

def assess(support=(), contra=(), evidence=ROWS):
    return evaluate_hypothesis(key="example", statement="Synthetic hypothesis",
                               scope="work", supporting_ids=support,
                               contradicting_ids=contra, evidence=evidence)

class HypothesisTests(unittest.TestCase):
    def test_unassessed(self):
        h = assess()
        self.assertEqual(h.status, "unassessed")
        self.assertEqual(h.uncertainty, "no evidence")

    def test_supported_without_numeric_confidence(self):
        h = assess(("s1",))
        self.assertEqual(h.status, "supported")
        self.assertIn("unknown", h.uncertainty)

    def test_conflicting_evidence_retained(self):
        h = assess(("s1",), ("c1",))
        self.assertEqual(h.status, "contested")
        self.assertEqual(h.supporting_ids, ("s1",))
        self.assertEqual(h.contradicting_ids, ("c1",))

    def test_out_of_scope_refused(self):
        with self.assertRaises(ValueError):
            assess(("other",))

    def test_unknown_evidence_refused(self):
        with self.assertRaises(ValueError):
            assess(("nonexistent",))

    def test_disputed_evidence_refused(self):
        with self.assertRaises(ValueError):
            assess(("disputed",))

    def test_same_evidence_both_sides_refused(self):
        with self.assertRaises(ValueError):
            assess(("s1",), ("s1",))

    def test_wildcard_scope_refused(self):
        with self.assertRaises(ValueError):
            evaluate_hypothesis(key="k", statement="s", scope="*",
                                supporting_ids=(), contradicting_ids=(), evidence=ROWS)

if __name__ == "__main__":
    unittest.main()
