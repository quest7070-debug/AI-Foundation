"""Fast path's strict localhost Ollama contract. No real model is called."""
from __future__ import annotations

import io
import json
from unittest.mock import patch
import unittest

from ai_foundation.agent import AgentRequest, AgentResult
from ai_foundation.development_compact_edit import (
    CompactEditProposalAgent, OneFastThenDeepAgent,
)
from ai_foundation.local_ollama_fast import (
    DirectLocalOllamaTextAgent, MODEL, LOCAL_URL, OUTPUT_LIMIT,
)


def _response(*, content='{"search":"x = 1","replace":"x = 2"}',
              model=MODEL, think=None, done=True, reason="stop",
              eval_count=90, duration=15_000_000_000):
    result={
        "model":model, "done":done,"done_reason":reason,
        "message":{"role":"assistant","content":content},
        "eval_count":eval_count,"eval_duration":duration,
        "prompt_eval_count":400,"load_duration":120_000_000,
    }
    if think is not None:
        result["message"]["thinking"]=think
    return io.BytesIO(json.dumps(result).encode())


class DirectLocalFastTests(unittest.TestCase):
    def test_fixed_loopback_nonthinking_and_exact_metrics(self):
        seen=[]
        def fake_http(req, timeout):
            self.assertEqual(req.get_full_url(),LOCAL_URL)
            self.assertEqual(req.get_method(),"POST")
            self.assertEqual(timeout,150)
            payload=json.loads(req.data)
            seen.append(payload)
            return _response()
        direct=DirectLocalOllamaTextAgent()
        with patch("ai_foundation.local_ollama_fast._OPENER.open",
                   side_effect=fake_http):
            result=direct.run(AgentRequest("Only this fixed approved edit"))
        self.assertEqual(len(seen),1)
        self.assertEqual(seen[0]["model"],MODEL)
        self.assertIs(seen[0]["think"],False)
        self.assertIs(seen[0]["stream"],False)
        self.assertEqual(seen[0]["options"]["num_predict"],OUTPUT_LIMIT)
        self.assertEqual(seen[0]["options"]["num_ctx"],32768)
        self.assertNotIn("tools",seen[0])
        self.assertTrue(direct.last_metrics["completed"])
        self.assertEqual(direct.last_metrics["eval_tokens_per_second"],6)
        self.assertEqual(direct.calls,1)
        self.assertIn("search",result.output)
        self.assertNotIn("content",direct.last_metrics)

    def test_adapter_accepts_short_patch_and_reconstructs_file(self):
        def fake_http(req, timeout):
            return _response()
        raw=DirectLocalOllamaTextAgent()
        compact=CompactEditProposalAgent(raw)
        packet=json.dumps({"instruction":"Fix assigned source",
                           "current_source":"x = 1\n",
                           "test_feedback":"host fixed test failed"})
        with patch("ai_foundation.local_ollama_fast._OPENER.open",
                   side_effect=fake_http):
            answer=compact.run(AgentRequest(packet))
        self.assertEqual(answer.output,"x = 2\n")

    def test_incorrect_model_or_unverified_reply_is_denied(self):
        for response in (
            lambda:_response(model="other"),
            lambda:_response(done=False),
            lambda:_response(content=""),
            lambda:_response(think="reasoning text"),
            lambda:_response(reason="length"),
            lambda:_response(eval_count=0),
        ):
            with self.subTest(response=response):
                with patch("ai_foundation.local_ollama_fast._OPENER.open",
                           side_effect=lambda *a, **kw:response()):
                    with self.assertRaises(ValueError):
                        DirectLocalOllamaTextAgent().run(
                            AgentRequest("approved code task"))

    def test_network_timeout_is_not_automatically_replayed(self):
        raw=DirectLocalOllamaTextAgent()
        deep=type("Deep",(),{"run":lambda self,request:
                           AgentResult("should not run")})()
        wrapper=OneFastThenDeepAgent(CompactEditProposalAgent(raw),deep)
        packet=json.dumps({"instruction":"fix","current_source":"x = 1\n",
                           "test_feedback":"red"})
        with patch("ai_foundation.local_ollama_fast._OPENER.open",
                   side_effect=TimeoutError("mocked bounded local timeout")) as mock:
            with self.assertRaises(TimeoutError):
                wrapper.run(AgentRequest(packet))
        self.assertEqual(mock.call_count,1)
        self.assertEqual(raw.calls,1)
        self.assertEqual(wrapper.calls,1)
        self.assertFalse(raw.last_metrics["completed"])

    def test_bad_model_text_reuses_one_existing_deep_repair(self):
        def fake_http(req,timeout):
            return _response(content="not json")
        raw=DirectLocalOllamaTextAgent()
        class Deep:
            def __init__(self): self.calls=0
            def run(self, request):
                self.calls+=1
                return AgentResult("x = 2\n")
        deep=Deep()
        first=OneFastThenDeepAgent(CompactEditProposalAgent(raw),deep)
        packet=json.dumps({"instruction":"fix","current_source":"x = 1\n",
                           "test_feedback":"red"})
        with patch("ai_foundation.local_ollama_fast._OPENER.open",
                   side_effect=fake_http):
            with self.assertRaises(SyntaxError):
                first.run(AgentRequest(packet))
        result=first.run(AgentRequest(packet))
        self.assertEqual(result.output,"x = 2\n")
        self.assertEqual(deep.calls,1)
        self.assertEqual(raw.calls,1)
        self.assertEqual(first.calls,2)

    def test_finished_but_truncated_fast_output_uses_existing_deep_repair(self):
        class Deep:
            def __init__(self): self.n=0
            def run(self, request):
                self.n+=1
                return AgentResult("x = 2\\n")
        deep=Deep()
        raw=DirectLocalOllamaTextAgent()
        combined=OneFastThenDeepAgent(CompactEditProposalAgent(raw),deep)
        packet=json.dumps({"instruction":"fix","current_source":"x = 1\\n",
                           "test_feedback":"test red"})
        with patch("ai_foundation.local_ollama_fast._OPENER.open",
                   side_effect=lambda *a,**kw:_response(
                       content='{"search":"x = 1"',reason="length")) as req:
            with self.assertRaises(SyntaxError):
                combined.run(AgentRequest(packet))
        result=combined.run(AgentRequest(packet))
        self.assertEqual(result.output,"x = 2\\n")
        self.assertEqual(deep.n,1)
        self.assertEqual(req.call_count,1)

    def test_prompt_and_http_body_bounded(self):
        with self.assertRaisesRegex(ValueError,"INVALID_FAST_PROPOSAL_PROMPT"):
            DirectLocalOllamaTextAgent().run(AgentRequest("x"*50000))
        with patch("ai_foundation.local_ollama_fast._OPENER.open",
                   return_value=io.BytesIO(b"x"*70000)):
            with self.assertRaisesRegex(ValueError,"LOCAL_MODEL_RESPONSE_TOO_LARGE"):
                DirectLocalOllamaTextAgent().run(AgentRequest("approved edit"))


if __name__=="__main__":
    unittest.main()
