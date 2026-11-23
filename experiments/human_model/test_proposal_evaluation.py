import unittest
from proposal_evaluation import Proposal, evaluate_proposals

EVIDENCE = [
    {"id": "s", "scope": "work", "disputed": 0},
    {"id": "c", "scope": "work", "disputed": 0},
    {"id": "secret", "scope": "personal", "disputed": 0},
]

def proposal(producer, support=(), contra=(), scope="work"):
    return Proposal(producer, "1", "2026-10-31T00:00:00Z",
                    "hypothesis-1", "synthetic statement", scope, support, contra)

class ProposalEvaluationTests(unittest.TestCase):
    def test_multi_producer_disagreement_retained(self):
        result = evaluate_proposals(
            proposals=[proposal("oss-a", ("s",)), proposal("oss-b", ("s",), ("c",))],
            evidence=EVIDENCE)
        self.assertTrue(result["producer_disagreement"])
        self.assertIsNone(result["consensus"])

    def test_untrusted_proposal_cannot_reference_unknown_evidence(self):
        with self.assertRaises(ValueError):
            evaluate_proposals(proposals=[proposal("oss-a", ("invented",))], evidence=EVIDENCE)

    def test_untrusted_proposal_cannot_reference_cross_scope_evidence(self):
        with self.assertRaises(ValueError):
            evaluate_proposals(proposals=[proposal("oss-a", ("secret",))], evidence=EVIDENCE)

    def test_duplicate_producer_revision_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_proposals(proposals=[proposal("oss-a"), proposal("oss-a")], evidence=EVIDENCE)

    def test_empty_proposals_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_proposals(proposals=[], evidence=EVIDENCE)

if __name__ == "__main__":
    unittest.main()
