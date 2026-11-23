"""Independent host-fixed RED baseline: Pydantic AgentPort must not forge a None result.

E2E acceptance target: src/ai_foundation/agent.py only.
This test uses no model, network, credentials or external service.
"""
import unittest
from types import SimpleNamespace

from ai_foundation.agent import AgentRequest, PydanticAgentPort


class AgentOutputBoundaryTests(unittest.TestCase):
    def test_missing_model_output_is_rejected_not_stringified(self):
        class NoOutput:
            def run_sync(self, instruction, **kwargs):
                return SimpleNamespace(output=None)

        port = PydanticAgentPort(NoOutput())
        with self.assertRaises((ValueError, TypeError)):
            port.run(AgentRequest("Return a bounded patch proposal"))

    def test_explicit_text_output_is_unchanged(self):
        class ValidOutput:
            def run_sync(self, instruction, **kwargs):
                return SimpleNamespace(output="source = 1\n")

        self.assertEqual(
            PydanticAgentPort(ValidOutput()).run(
                AgentRequest("Return a bounded patch proposal")).output,
            "source = 1\n",
        )


if __name__ == "__main__":
    unittest.main()
