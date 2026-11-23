import unittest
from hypothesis_engine import Hypothesis
from temporal_comparison import ModelSnapshot, compare_snapshots

def snap(producer, revision, status, support=(), contra=()):
    return ModelSnapshot(producer, revision, "2026-10-31T00:00:00Z",
                         Hypothesis("k", "synthetic", "work", support, contra, status, "unknown"))

class TemporalComparisonTests(unittest.TestCase):
    def test_disagreement_preserved(self):
        result = compare_snapshots([
            snap("model-a", "1", "supported", ("s1",)),
            snap("model-b", "1", "contested", ("s1",), ("c1",)),
        ])
        self.assertTrue(result["producer_disagreement"])
        self.assertIsNone(result["consensus"])
        self.assertEqual(result["transitions"][0]["contradiction_added"], ["c1"])

    def test_revision_evidence_removal_visible(self):
        result = compare_snapshots([
            snap("model-a", "1", "supported", ("s1",)),
            snap("model-a", "2", "unassessed"),
        ])
        self.assertEqual(result["transitions"][0]["support_removed"], ["s1"])

    def test_cross_scope_rejected(self):
        second = snap("model-b", "1", "supported")
        bad = ModelSnapshot("model-b", "1", second.observed_at,
                            Hypothesis("k", "synthetic", "personal", (), (), "supported", "unknown"))
        with self.assertRaises(ValueError):
            compare_snapshots([snap("model-a", "1", "supported"), bad])

    def test_duplicate_revision_rejected(self):
        with self.assertRaises(ValueError):
            compare_snapshots([snap("a", "1", "supported"), snap("a", "1", "contested")])

if __name__ == "__main__":
    unittest.main()
