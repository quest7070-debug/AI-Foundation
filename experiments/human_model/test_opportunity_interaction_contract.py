"""Regression tests using only synthetic events and public snapshot locators."""
import unittest
from opportunity_interaction_contract import OpportunityEvent, classify

URI = "https://chatgpt.com/share/6ac819d7-24bc-83e8-9eb7-ede28ed9ea43"

def event(locator, actor, kind, **kw):
    return OpportunityEvent(source_uri=URI, source_locator=locator, actor=actor,
                            event=kind, quality="direct", target_id="strata",
                            text="synthetic placeholder", **kw)

class OpportunityInteractionTests(unittest.TestCase):
    def test_question_is_not_approval(self):
        events = [event("M04", "assistant", "assistant_proposal"),
                  event("M05", "user", "user_question"),
                  event("M06", "assistant", "assistant_retraction",
                        supersedes_locator="M04")]
        self.assertEqual(classify(events),
                         {"total": 3, "direct": 3, "summary_only": 0,
                          "user_approvals": 0, "assistant_proposals": 1,
                          "verified_outcomes": 0})

    def test_assistant_cannot_create_user_approval(self):
        with self.assertRaises(ValueError):
            event("M07", "assistant", "user_approval")

    def test_summary_cannot_claim_verified_outcome(self):
        with self.assertRaises(ValueError):
            OpportunityEvent(URI, "2026-10-12", "automation",
                             "verified_outcome", "summary_only", "oss",
                             "reported only")

    def test_summary_cannot_invent_message_id(self):
        with self.assertRaises(ValueError):
            OpportunityEvent(URI, "internal_message_id:invented", "assistant",
                             "assistant_proposal", "summary_only", "oss",
                             "reported only")

    def test_retraction_requires_original(self):
        with self.assertRaises(ValueError):
            classify([event("M06", "assistant", "assistant_retraction",
                            supersedes_locator="M04")])

    def test_duplicate_event_rejected(self):
        e = event("M04", "assistant", "assistant_proposal")
        with self.assertRaises(ValueError):
            classify([e, e])

    def test_assistant_claim_not_verified_outcome(self):
        events = [event("M08", "assistant", "assistant_execution_claim")]
        self.assertEqual(classify(events)["verified_outcomes"], 0)

if __name__ == "__main__":
    unittest.main()
