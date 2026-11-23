import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_foundation.line_history import LineHistoryArchive, parse_line_txt

EXPORTED = (
    "[LINE] トーク履歴\n"
    "保存日時：2026/11/11\n"
    "2026/11/10(火)\n"
    "08:12\t友人\tおはよう\n"
    "08:13\t自分\tおはよう！\n"
    "08:13\t自分\tおはよう！\n"
    "08:15\t友人\t本文1\n続き2\n"
).encode("utf-8")


class LineHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.archive = LineHistoryArchive(Path(self.tmp.name) / "private" / "line.db", owner="mine")

    def test_self_sender_aliases_must_be_explicit_exact_sequence(self):
        for aliases in ("自分", {"自分"}, {"自分": True}, ("",), ("x" * 301,)):
            with self.subTest(aliases=aliases):
                with self.assertRaisesRegex(ValueError, "explicit self_names"):
                    parse_line_txt(EXPORTED, conversation_key="chat-001",
                                   self_names=aliases)
        events, _ = parse_line_txt(EXPORTED, conversation_key="chat-001",
                                   self_names=("自分",))
        self.assertEqual(sum(x["direction"] == "outgoing" for x in events), 2)

    def test_txt_preserves_self_sent_and_same_minute_duplicates(self):
        events, receipt = parse_line_txt(EXPORTED, conversation_key="chat-001", self_names=("自分",))
        self.assertEqual(receipt["parsed"], 4)
        self.assertEqual([x["direction"] for x in events],
                         ["incoming", "outgoing", "outgoing", "incoming"])
        self.assertNotEqual(events[1]["source_event_id"], events[2]["source_event_id"])
        self.assertEqual(events[3]["text"], "本文1\n続き2")
        self.assertFalse(receipt["complete"])
        self.assertEqual(self.archive.ingest(events)["inserted"], 4)
        self.assertEqual(self.archive.ingest(events)["already_present"], 4)
        self.assertEqual(self.archive.status()["by_source_direction"][("txt", "outgoing")], 2)

    def test_txt_import_entrypoints_reject_nonsequence_self_aliases_atomically(self):
        # The parser must see the caller's original type; converting a string
        # to tuple silently splits it into characters and corrupts self-sent tags.
        for aliases in ("自分", {"自分"}, {"自分": True}):
            with self.subTest(entry="single", aliases=aliases):
                with self.assertRaisesRegex(ValueError, "explicit self_names"):
                    self.archive.import_txt(
                        EXPORTED, conversation_key="chat-001", self_names=aliases)
                self.assertEqual(self.archive.status()["by_source_direction"], {})
            with self.subTest(entry="batch", aliases=aliases):
                with self.assertRaisesRegex(ValueError, "explicit self_names"):
                    self.archive.import_txt_batch([
                        (EXPORTED, "chat-001", ("自分",)),
                        (EXPORTED, "chat-002", aliases),
                    ])
                self.assertEqual(self.archive.status()["by_source_direction"], {})
        result = self.archive.import_txt(
            EXPORTED, conversation_key="chat-001", self_names=["自分"])
        self.assertEqual(result["inserted"], 4)
        self.assertEqual(self.archive.status()["by_source_direction"]
                         [("txt", "outgoing")], 2)

    def test_batch_import_is_one_transaction_and_replay_is_idempotent(self):
        def broken_exports():
            yield EXPORTED, "chat-001", ("自分",)
            yield b"\xff", "chat-002", ("自分",)

        with self.assertRaisesRegex(ValueError, "unsupported TXT encoding"):
            self.archive.import_txt_batch(broken_exports())
        self.assertEqual(self.archive.status()["by_source_direction"], {})

        documents = [
            (EXPORTED, "chat-001", ("自分",)),
            (EXPORTED, "chat-002", ("自分",)),
        ]
        first = self.archive.import_txt_batch(documents)
        self.assertEqual(first["exports_processed"], 2)
        self.assertEqual(first["parsed"], 8)
        self.assertEqual(first["inserted"], 8)
        self.assertEqual(first["already_present"], 0)
        self.assertFalse(first["account_complete"])
        second = self.archive.import_txt_batch(documents)
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(second["already_present"], 8)
        self.assertEqual(self.archive.status()["by_source_direction"][("txt", "outgoing")], 4)

    def test_cli_manifest_rejects_late_escape_without_partial_history(self):
        import json
        import sys
        from unittest.mock import patch
        from scripts import line_history_import

        root = Path(self.tmp.name) / "manifest-root"
        root.mkdir()
        (root / "first.txt").write_bytes(EXPORTED)
        manifest = root / "exports.json"
        manifest.write_text(json.dumps({"chats": [
            {"file": "first.txt", "conversation_key": "chat-001",
             "self_names": ["自分"]},
            {"file": "../outside.txt", "conversation_key": "chat-002",
             "self_names": ["自分"]},
        ]}, ensure_ascii=False), encoding="utf-8")
        db = root / "private" / "manifest.db"
        argv = ["line_history_import.py", "--db", str(db),
                "--owner", "mine", "--manifest", str(manifest)]
        with patch.object(sys, "argv", argv):
            with self.assertRaisesRegex(ValueError, "manifest file"):
                line_history_import.main()
        archive = LineHistoryArchive(db, owner="mine")
        self.assertEqual(archive.status()["by_source_direction"], {})

    def test_cli_jsonl_duplicate_key_late_in_file_rolls_back(self):
        import json
        import sys
        from unittest.mock import patch
        from scripts import line_history_import

        root = Path(self.tmp.name) / "capture-stream"
        root.mkdir()
        journal = root / "events.jsonl"
        first = {
            "schema": "line-capture/v1", "kind": "message",
            "source": "notification", "source_event_id": "capture-1",
            "conversation_key": "notify:owner-approved-room",
            "actor": "friend", "direction": "incoming", "text": "hello",
            "observed_at": "2026-11-11T10:00:00+09:00",
            "quality": "NOTIFICATION",
        }
        journal.write_text(json.dumps(first, ensure_ascii=False) + "\n" +
                           '{"schema":"line-capture/v1","schema":"line-capture/v1"}\n',
                           encoding="utf-8")
        db = root / "private" / "events.db"
        argv = ["line_history_import.py", "--db", str(db),
                "--owner", "mine", "--jsonl", str(journal)]
        with patch.object(sys, "argv", argv):
            with self.assertRaisesRegex(ValueError, "DUPLICATE_JSON_KEY"):
                line_history_import.main()
        self.assertEqual(LineHistoryArchive(db, owner="mine").status()
                         ["by_source_direction"], {})

        journal.write_text(json.dumps(first, ensure_ascii=False) + "\n",
                           encoding="utf-8")
        with patch.object(sys, "argv", argv):
            line_history_import.main()
        with patch.object(sys, "argv", argv):
            line_history_import.main()
        self.assertEqual(LineHistoryArchive(db, owner="mine").status()
                         ["by_source_direction"][("notification", "incoming")], 1)

    def test_no_cross_source_silent_collapse(self):
        self.archive.import_txt(EXPORTED, conversation_key="chat-001", self_names=["自分"])
        capture = {
            "schema": "line-capture/v1", "kind": "message", "source": "screen",
            "source_event_id": "screen:abc", "conversation_key": "chat-001",
            "actor": None, "direction": "outgoing_candidate",
            "text": "おはよう！", "event_time": None,
            "observed_at": "2026-11-10T08:14:00+09:00",
            "quality": "UNVERIFIED_UI_TEXT"}
        self.assertEqual(self.archive.ingest([capture])["inserted"], 1)
        self.assertEqual(self.archive.status()["unverified_screen_observations"], 1)
        self.assertEqual(self.archive.ingest([capture])["already_present"], 1)

    def test_reused_source_id_with_conflicting_text_is_rejected(self):
        event = {"schema": "line-capture/v1", "kind": "message",
                 "source": "notification", "source_event_id": "n1",
                 "conversation_key": "notify:friend", "actor": "friend",
                 "direction": "incoming", "text": "first",
                 "observed_at": "2026-11-11T10:00:00+09:00",
                 "quality": "NOTIFICATION"}
        self.assertEqual(self.archive.ingest([event])["inserted"], 1)
        self.assertEqual(self.archive.ingest([event])["already_present"], 1)
        with self.assertRaisesRegex(ValueError, "SOURCE_EVENT_ID_CONFLICT"):
            self.archive.ingest([{**event, "text": "changed"}])

    def test_notification_replay_allows_new_sighting_not_changed_message_time(self):
        original = {
            "schema": "line-capture/v1", "kind": "message",
            "source": "notification", "source_event_id": "same-id",
            "conversation_key": "notify:friend", "actor": "friend",
            "direction": "incoming", "text": "same",
            "event_time": "2026-11-11T09:00:00+09:00",
            "observed_at": "2026-11-11T09:01:00+09:00",
            "quality": "NOTIFICATION",
        }
        self.assertEqual(self.archive.ingest([original])["inserted"], 1)
        self.assertEqual(self.archive.ingest([original])["already_present"], 1)
        # Android MessagingStyle re-emits the same message with a later
        # callback time. A source-ID replay must not make the import unusable.
        self.assertEqual(self.archive.ingest([{**original,
            "observed_at": "2026-11-11T09:03:00+09:00"}])["already_present"], 1)
        with self.assertRaisesRegex(ValueError, "SOURCE_EVENT_ID_CONFLICT"):
            self.archive.ingest([{**original,
                "event_time": "2026-11-11T09:02:00+09:00"}])
        self.assertEqual(self.archive.status()["by_source_direction"]
                         [("notification", "incoming")], 1)

    def test_screen_reobserved_in_one_bucket_keeps_source_idempotence(self):
        screen = {
            "schema": "line-capture/v1", "kind": "message",
            "source": "screen", "source_event_id": "ui:one-bucket",
            "conversation_key": "screen:unresolved", "actor": None,
            "direction": "outgoing_candidate", "text": "same screen content",
            "event_time": "2026-11-11T09:00:01+09:00",
            "observed_at": "2026-11-11T09:00:01+09:00",
            "quality": "UNVERIFIED_UI_TEXT",
        }
        self.assertEqual(self.archive.ingest([screen])["inserted"], 1)
        later = {**screen,
                 "event_time": "2026-11-11T09:00:12+09:00",
                 "observed_at": "2026-11-11T09:00:12+09:00"}
        self.assertEqual(self.archive.ingest([later])["already_present"], 1)
        with self.assertRaisesRegex(ValueError, "SOURCE_EVENT_ID_CONFLICT"):
            self.archive.ingest([{**later, "text": "different text"}])

    def test_txt_source_id_binds_exact_event_and_observation_times(self):
        records, _ = parse_line_txt(EXPORTED, conversation_key="chat-1",
                                    self_names=("自分",))
        first = records[0]
        self.assertEqual(self.archive.ingest([first])["inserted"], 1)
        for field, changed in (
            ("event_time", "2026-11-11T09:02:00+09:00"),
            ("observed_at", "2026-11-11T09:03:00+09:00"),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "SOURCE_EVENT_ID_CONFLICT"):
                    self.archive.ingest([{**first, field: changed}])

    def test_reused_coverage_id_with_changed_window_is_rejected(self):
        original = {
            "schema": "line-capture/v1", "kind": "coverage",
            "source": "notification", "source_event_id": "listener-1",
            "quality": "LISTENER_CONNECTED",
            "observed_at": "2026-11-11T10:00:00+09:00",
            "event_time": "2026-11-11T10:01:00+09:00",
        }
        self.assertEqual(self.archive.ingest([original])["inserted"], 1)
        self.assertEqual(self.archive.ingest([original])["already_present"], 1)
        for field, changed in (
            ("event_time", "2026-11-11T10:02:00+09:00"),
            ("observed_at", "2026-11-11T10:03:00+09:00"),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "SOURCE_EVENT_ID_CONFLICT"):
                    self.archive.ingest([{**original, field: changed}])
        self.assertEqual(self.archive.status()["service_coverage_markers"]
                         [("notification", "LISTENER_CONNECTED")], 1)

    def test_notification_never_certifies_outgoing(self):
        event = {"schema": "line-capture/v1", "kind": "message",
                 "source": "notification", "source_event_id": "n1",
                 "conversation_key": "friend", "actor": "friend",
                 "direction": "outgoing", "text": "test",
                 "observed_at": "2026-11-10T08:14:00+09:00",
                 "quality": "NOTIFICATION"}
        with self.assertRaisesRegex(ValueError, "cannot certify"):
            self.archive.ingest([event])

    def test_unzoned_and_unsupported_input_rejected_without_partial_commit(self):
        bad = {"schema": "line-capture/v1", "kind": "message", "source": "screen",
               "source_event_id": "a", "conversation_key": "unknown",
               "actor": None, "direction": "unknown", "text": "s",
               "observed_at": "2026-11-11T10:00:00",
               "quality": "UNVERIFIED_UI_TEXT"}
        with self.assertRaisesRegex(ValueError, "timezone"):
            self.archive.ingest([bad])
        self.assertEqual(self.archive.status()["by_source_direction"], {})

    def test_coverage_receipt_does_not_claim_complete(self):
        event = {"schema": "line-capture/v1", "kind": "coverage",
                 "source": "notification", "source_event_id": "connected-1",
                 "observed_at": "2026-11-11T10:00:00+09:00",
                 "quality": "LISTENER_CONNECTED"}
        self.archive.ingest([event])
        self.assertEqual(self.archive.status()["service_coverage_markers"]
                         [("notification", "LISTENER_CONNECTED")], 1)
        self.assertFalse(self.archive.status()["account_complete"])

    def test_klm_pointer_does_not_expose_private_content(self):
        self.archive.import_txt(EXPORTED, conversation_key="chat-001", self_names=["自分"])
        pointers = self.archive.klm_source_pointers(limit=5)
        self.assertEqual(len(pointers), 4)
        self.assertTrue(all(p.privacy == "private" and p.system == "other" for p in pointers))
        self.assertTrue(all("おはよう" not in str(p) for p in pointers))

    def test_reconcile_does_not_claim_missing_as_certain_and_requires_chat_mapping(self):
        self.archive.import_txt(EXPORTED, conversation_key="chat-001", self_names=["自分"])
        with self.assertRaisesRegex(ValueError, "unresolved"):
            self.archive.reconcile_export_window(conversation_key="chat-001",
                                                  capture_keys=["screen:unresolved"])
        result = self.archive.reconcile_export_window(conversation_key="chat-001",
                            capture_keys=["notify:explicit-room"])
        self.assertEqual(result["exported_messages"], 4)
        self.assertEqual(result["not_observed_in_live_capture"], 4)
        self.assertFalse(result["coverage_certified"])
        self.assertEqual(len(result["unresolved_export_event_ids"]), 4)

    def test_reconciliation_requires_exact_capture_chat_sequence(self):
        self.archive.import_txt(EXPORTED, conversation_key="chat-001",
                                self_names=["自分"])
        # A raw string used to be iterated one character at a time, silently
        # reporting all exported messages as missing from live capture.
        for invalid in ("notify:friend", {"notify:friend"},
                        {"notify:friend": True}, (), [], None, 7,
                        ["capture:" + str(i) for i in range(21)]):
            with self.subTest(capture_keys=invalid):
                with self.assertRaisesRegex(
                        ValueError, "explicit bounded capture chat mapping required"):
                    self.archive.reconcile_export_window(
                        conversation_key="chat-001", capture_keys=invalid)
        for aliases in (["notify:friend"], ("notify:friend",)):
            with self.subTest(valid=aliases):
                result = self.archive.reconcile_export_window(
                    conversation_key="chat-001", capture_keys=aliases)
                self.assertEqual(result["exported_messages"], 4)
                self.assertFalse(result["coverage_certified"])

    def test_local_archive_mode_and_encoding(self):
        self.assertEqual(os.stat(self.archive.path).st_mode & 0o777, 0o600)
        self.assertEqual(self.archive.import_txt(EXPORTED, conversation_key="x",
                         self_names=["自分"])["parsed"], 4)
        with self.assertRaisesRegex(ValueError, "explicit self_names"):
            parse_line_txt(EXPORTED, conversation_key="x", self_names=())

    def test_different_owner_cannot_use_private_archive(self):
        with self.assertRaisesRegex(PermissionError, "private"):
            os.chmod(self.archive.path, 0o644)
            LineHistoryArchive(self.archive.path, owner="other")
        os.chmod(self.archive.path, 0o600)
        with self.assertRaisesRegex(PermissionError, "different owner"):
            LineHistoryArchive(self.archive.path, owner="other")


if __name__ == "__main__":
    unittest.main()
