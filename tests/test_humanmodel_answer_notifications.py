"""Synthetic real producer -> durable notice -> UI; no model or owner data."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from ai_foundation.core import CanonContract, Decision, TaskPlan
from ai_foundation.human_model_primary_review import HumanModelPrimaryReview
from ai_foundation.human_renderer import render
from ai_foundation.human_view import HumanView
from ai_foundation.notification_boundary import project_push
from ai_foundation.primary_review_events import PrimaryReviewTransitions, primary_review_notices
from ai_foundation.question_bridge import question_identity


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class AnswerNotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "work.db"
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE work_steps (job_id TEXT, status TEXT)")
        self.events = PrimaryReviewTransitions(self.path)
        self.plan = TaskPlan("task-1", "write", "synthetic.py",
                             canon_revision="canon-1", effect_id="effect-1")
        self.bundle = {"pending_id": "pending-1", "task_id": "task-1", "session_id": "s-1",
                       "questions": [{"question_id": "q-1", "prompt": "<script>private question</script>",
                                      "options": [{"option_id": "a", "label": "選択A <img onerror=bad>"},
                                                  {"option_id": "b", "label": "選択B"}]}]}
        self.answers = [{"question_id": "q-1", "selected_options": ["a"]}]
        content = json.dumps({
            "schema": "foundation-explicit-delegation/v1",
            "question_digest": question_identity(self.bundle).digest,
            "answers": self.answers,
            "answer_sha256": sha(json.dumps(self.answers, sort_keys=True, ensure_ascii=False,
                                            separators=(",", ":"))),
            "action": self.plan.action, "target_sha256": sha(self.plan.target),
            "effect_id": self.plan.effect_id, "canon_revision": self.plan.canon_revision})
        self.snapshot = {"status": "AVAILABLE", "source": "HumanModel",
                         "execution_authority": False, "snapshot_sha256": "c" * 64,
                         "view_revision": "view-1", "records": [{
                             "kind": "decision", "scope": "foundation", "content": content,
                             "content_sha256": sha(content), "disputed": False,
                             "source_uri": "synthetic:PRIVATE_LEDGER_SOURCE", "source_revision": "1",
                             "observed_at": "2026-11-17"}]}

    def review(self, *, allowed=True):
        reviewer = HumanModelPrimaryReview(
            owner_id="owner", context=SimpleNamespace(owner_id="owner", read=lambda *a: json.dumps(self.snapshot)),
            scope="foundation", guard=SimpleNamespace(preflight=lambda *a: Decision.ALLOW if allowed else Decision.DENY),
            plan=self.plan, canon=CanonContract("synthetic", "canon-1"), transitions=self.events)
        return reviewer.review(self.bundle)

    def test_real_answer_survives_restart_and_no_confirmation_is_required(self):
        result = self.review()
        self.assertEqual(result.answer, self.answers)
        rows = primary_review_notices(self.path)
        answer = next(n for n in rows if n.automatic_answer)
        self.assertEqual(answer.level, 2)
        self.assertFalse(answer.actionable)
        self.assertFalse(answer.input_required)
        self.assertIn("選択A", answer.automatic_answer)
        self.assertNotIn("選択B", answer.automatic_answer)
        self.assertIn("Muse", answer.detail_ja)
        self.assertIn(question_identity(self.bundle).digest, answer.detail_ja)
        self.assertNotIn("PRIVATE_LEDGER_SOURCE", repr(rows))
        PrimaryReviewTransitions(self.path)
        self.assertEqual(primary_review_notices(self.path), rows)
        self.review()
        self.assertEqual(primary_review_notices(self.path), rows)

    def test_ui_escapes_answer_and_echo_and_push_keep_it_private(self):
        self.review()
        rows = primary_review_notices(self.path)
        view = HumanView("READY", notices=rows)
        html = render(view)
        self.assertIn("HumanModel 自動回答", html)
        self.assertIn("&lt;script&gt;private question&lt;/script&gt;", html)
        self.assertNotIn("<script>private question</script>", html)
        self.assertNotIn("<img onerror=bad>", html)
        self.assertNotIn("private question", render(view, surface="echo"))
        pushed = project_push({"notices": [n.__dict__ for n in rows]})
        self.assertEqual(len(pushed), 2)
        self.assertNotIn("private question", repr(pushed))
        self.assertNotIn("選択A", repr(pushed))

    def test_guard_denied_never_displays_an_answer(self):
        result = self.review(allowed=False)
        self.assertIsNone(result.answer)
        self.assertTrue(all(not n.automatic_answer for n in primary_review_notices(self.path)))

    def test_api_preserves_exact_correction_target_and_separate_work_state(self):
        from ai_foundation.core import GuardState
        from ai_foundation.guard import GuardCore
        from ai_foundation.operator_actions import OperatorActions
        from ai_foundation.operator_server import OperatorApplication
        from ai_foundation.productization import FoundationConfig
        self.review()
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO work_steps VALUES (?,?)", ("task-1", "RUNNING"))
        app_root = Path(self.temp.name) / "operator"
        app_root.mkdir()
        app = OperatorApplication(FoundationConfig(str(app_root)),
                                  OperatorActions(GuardCore(GuardState())),
                                  operational_notices=lambda: primary_review_notices(self.path))
        payload = json.loads(json.dumps(app.human_payload(), ensure_ascii=False))
        answer = next(n for n in payload["notices"] if n["automatic_answer"])
        ref = answer["answer_reference"]
        self.assertEqual(ref["task_id"], "task-1")
        self.assertEqual(ref["question_digest"], question_identity(self.bundle).digest)
        self.assertEqual(ref["related_work_status"], "RUNNING")
        self.assertTrue(ref["current_generation"])
        newer = sha("new question generation")
        self.events.started("task-1", newer)
        historical = next(n for n in primary_review_notices(self.path) if n.automatic_answer)
        self.assertFalse(historical.answer_reference["current_generation"])
        self.assertIn("過去の判断履歴", historical.detail_ja)

    def test_echo_http_poll_does_not_receive_private_answer(self):
        from http.client import HTTPConnection
        from http.server import HTTPServer
        from threading import Thread
        from ai_foundation.core import GuardState
        from ai_foundation.guard import GuardCore
        from ai_foundation.operator_actions import OperatorActions
        from ai_foundation.operator_server import OperatorApplication, make_handler
        from ai_foundation.productization import FoundationConfig
        self.review()
        app_root = Path(self.temp.name) / "http-operator"
        app_root.mkdir()
        app = OperatorApplication(FoundationConfig(str(app_root)),
                                  OperatorActions(GuardCore(GuardState())),
                                  operational_notices=lambda: primary_review_notices(self.path))
        self.assertIn("fetch('/api/human/echo'", app.page('echo'))
        self.assertNotIn("fetch('/api/human'", app.page('echo'))
        with HTTPServer(("127.0.0.1", 0), make_handler(app)) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                client = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                try:
                    client.request("GET", "/api/human/echo", headers={"Host": "127.0.0.1"})
                    response = client.getresponse()
                    body = response.read().decode()
                    self.assertEqual(response.status, 200)
                    self.assertNotIn("private question", body)
                    self.assertNotIn("選択A", body)
                    self.assertNotIn("automatic_answer", body)
                    self.assertNotIn("answer_reference", body)
                    self.assertEqual(len(json.loads(body)["notices"]), 2)
                finally:
                    client.close()
            finally:
                server.shutdown()
                thread.join(timeout=3)

    def test_conflicting_answer_and_failed_outcome_cannot_overwrite(self):
        self.review()
        generation = question_identity(self.bundle).digest
        source_hash = self.snapshot["records"][0]["content_sha256"]
        with self.assertRaisesRegex(ValueError, "conflicting"):
            self.events.resolved("task-1", generation, "MATCHED_EXISTING_DELEGATION",
                                 evidence_sha256=source_hash, answer_text="different")
        with self.assertRaisesRegex(ValueError, "answer summary"):
            self.events.resolved("task-1", generation, "NO_MATCHING_EVIDENCE", answer_text="forged")

    def test_legacy_hash_only_reader_is_readonly_and_producer_migrates_without_backfill(self):
        legacy = Path(self.temp.name) / "legacy.db"
        with sqlite3.connect(legacy) as db:
            db.execute("CREATE TABLE work_steps (job_id TEXT, status TEXT)")
            db.execute("CREATE TABLE primary_review_transitions (job_id TEXT, generation_sha256 TEXT, "
                       "event TEXT, outcome TEXT, evidence_sha256 TEXT, created_at INTEGER, "
                       "PRIMARY KEY(job_id,generation_sha256,event))")
            db.execute("INSERT INTO primary_review_transitions VALUES (?,?,?,?,?,?)",
                       ("legacy", "d" * 64, "PRIMARY_REVIEW_RESOLVED", "MATCHED_EXISTING_DELEGATION", "", 1))
        before = legacy.read_bytes()
        self.assertFalse(primary_review_notices(legacy)[0].automatic_answer)
        self.assertEqual(legacy.read_bytes(), before)
        PrimaryReviewTransitions(legacy)
        self.assertFalse(primary_review_notices(legacy)[0].automatic_answer)


if __name__ == "__main__":
    unittest.main()
