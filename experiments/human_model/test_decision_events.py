"""Synthetic tests for explicit user decision events."""
import tempfile
import unittest
from pathlib import Path

from human_model_ledger import Ledger
from decision_events import DecisionEvent, current_decision, list_decisions, record_decision


class DecisionEventTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = Ledger(Path(self.temp.name) / "ledger.sqlite3")
        self.addCleanup(self.ledger.close)
        self.target = self.ledger.add(
            source_uri="synthetic:chat:1", source_revision="1",
            kind="observation", scope="work", content="synthetic chat record")
        self.other_scope_target = self.ledger.add(
            source_uri="synthetic:chat:2", source_revision="1",
            kind="observation", scope="personal", content="synthetic other scope")

    def event(self, **overrides):
        fields = dict(event_id="evt-1", transition="chat_to_concept",
                      target_id=self.target, scope="work",
                      action="accept", actor="user")
        fields.update(overrides)
        return DecisionEvent(**fields)

    def test_record_and_read_back(self):
        eid = record_decision(self.ledger, self.event(rationale="worth keeping"))
        rows = list_decisions(self.ledger, scope="work")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["evidence_id"], eid)
        self.assertEqual(rows[0]["transition"], "chat_to_concept")
        self.assertEqual(rows[0]["action"], "accept")
        self.assertEqual(rows[0]["rationale"], "worth keeping")
        current = current_decision(self.ledger, target_id=self.target, scope="work")
        self.assertEqual(current["evidence_id"], eid)

    def test_undecided_is_none_not_approval(self):
        self.assertIsNone(
            current_decision(self.ledger, target_id=self.target, scope="work"))

    def test_non_user_actor_refused(self):
        for actor in ("ai", "assistant", "model", "system", "gpt"):
            with self.assertRaises(ValueError):
                record_decision(self.ledger, self.event(actor=actor))

    def test_unknown_transition_and_action_refused(self):
        with self.assertRaises(ValueError):
            record_decision(self.ledger, self.event(transition="chat_to_profile"))
        with self.assertRaises(ValueError):
            record_decision(self.ledger, self.event(action="maybe"))

    def test_missing_or_cross_scope_target_refused(self):
        with self.assertRaises(ValueError):
            record_decision(self.ledger, self.event(target_id="nonexistent"))
        with self.assertRaises(ValueError):
            record_decision(
                self.ledger, self.event(target_id=self.other_scope_target))

    def test_idempotent_rerecord_and_conflict_refused(self):
        first = record_decision(self.ledger, self.event())
        again = record_decision(self.ledger, self.event())
        self.assertEqual(first, again)
        with self.assertRaises(ValueError):
            record_decision(self.ledger, self.event(action="reject"))

    def test_correction_supersedes_earlier_decision(self):
        first = record_decision(self.ledger, self.event())
        second = record_decision(
            self.ledger, self.event(event_id="evt-2", action="reject"),
            supersedes=first)
        current = current_decision(self.ledger, target_id=self.target, scope="work")
        self.assertEqual(current["evidence_id"], second)
        self.assertEqual(current["action"], "reject")
        self.assertEqual(len(list_decisions(self.ledger, scope="work")), 2)

    def test_supersede_non_decision_refused(self):
        with self.assertRaises(ValueError):
            record_decision(self.ledger, self.event(), supersedes=self.target)

    def test_scope_isolation(self):
        record_decision(self.ledger, self.event())
        self.assertEqual(list_decisions(self.ledger, scope="personal"), [])
        with self.assertRaises(ValueError):
            list_decisions(self.ledger, scope="*")


if __name__ == "__main__":
    unittest.main()
