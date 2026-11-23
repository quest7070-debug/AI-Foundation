import json
import unittest
from unittest.mock import patch
from ollama_proposal_runner import _local_url, generate_local_proposals

class LocalOllamaTests(unittest.TestCase):
    def test_localhost_only(self):
        self.assertEqual(_local_url("http://127.0.0.1:11434"),
                         "http://127.0.0.1:11434/api/chat")
        for url in ("https://example.com:11434", "http://10.0.0.1:11434",
                    "http://localhost:11434@evil.com:11434", "file:///tmp/x"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                _local_url(url)

    def test_no_evidence_means_no_network(self):
        with patch("ollama_proposal_runner.urlopen") as call:
            self.assertEqual(generate_local_proposals(model="test", evidence=[]), "[]")
            call.assert_not_called()

    def test_rejects_bad_model(self):
        with self.assertRaises(ValueError):
            generate_local_proposals(model="", evidence=[{"id":"a"}])

    def test_response_parsed_and_bounded(self):
        payload = [{"producer":"local","revision":"1","observed_at":"2026-11-01T00:00:00Z",
                    "key":"k","statement":"synthetic","scope":"work",
                    "supporting_ids":["a"],"contradicting_ids":[]}]
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, limit): return json.dumps(
                {"message":{"content":json.dumps(payload)}}).encode()
        with patch("ollama_proposal_runner.urlopen", return_value=Response()) as call:
            result = generate_local_proposals(
                model="local", evidence=[{"id":"a","scope":"work","content":"synthetic"}])
            self.assertEqual(len(json.loads(result)), 1)
            self.assertEqual(call.call_count, 1)

if __name__ == "__main__":
    unittest.main()
