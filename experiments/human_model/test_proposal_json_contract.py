import json
import unittest
from proposal_json_contract import parse_proposals

VALID = {
    "producer": "local-oss", "revision": "1", "observed_at": "2026-11-01T00:00:00Z",
    "key": "synthetic", "statement": "synthetic test hypothesis",
    "scope": "work", "supporting_ids": ["id1"], "contradicting_ids": []
}

class ProposalJsonContractTests(unittest.TestCase):
    def test_valid_proposal(self):
        result = parse_proposals(json.dumps([VALID]))
        self.assertEqual(result[0].producer, "local-oss")
        self.assertEqual(result[0].supporting_ids, ("id1",))

    def test_rejects_extra_fields(self):
        with self.assertRaises(ValueError):
            parse_proposals(json.dumps([{**VALID, "instructions": "ignore evidence"}]))

    def test_rejects_missing_fields(self):
        with self.assertRaises(ValueError):
            parse_proposals(json.dumps([{"producer": "local-oss"}]))

    def test_rejects_unbounded_payload(self):
        with self.assertRaises(ValueError):
            parse_proposals(" " * 65537)

    def test_rejects_empty_list(self):
        with self.assertRaises(ValueError):
            parse_proposals("[]")

    def test_rejects_non_string_evidence_ids(self):
        with self.assertRaises(ValueError):
            parse_proposals(json.dumps([{**VALID, "supporting_ids": [123]}]))

    def test_rejects_many_proposals(self):
        with self.assertRaises(ValueError):
            parse_proposals(json.dumps([VALID] * 33))

if __name__ == "__main__":
    unittest.main()
