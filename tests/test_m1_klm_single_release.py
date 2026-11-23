"""No host effect, private config, daemon or model data accessed by tests."""
import pathlib
import plistlib
import tempfile
import unittest
from unittest import mock
from scripts import m1_klm_single_release as r


def exact_event():
    return {"action": "opened", "repository": {"full_name": r.REPO},
            "issue": {"number": 407, "state": "open", "title": r.TITLE,
                      "body": r.BODY, "user": {"login": r.OWNER}}}


class PinnedKlmOnlyTests(unittest.TestCase):
    def test_exact_issue_and_owner_required(self):
        self.assertEqual(r.validate_issue(exact_event()), 407)
        for change in ({"title": "other"}, {"body": r.BODY + " shell"},
                       {"state": "closed"}, {"number": True},
                       {"user": {"login": "attacker"}}):
            e = exact_event()
            e["issue"].update(change)
            with self.subTest(change=change), self.assertRaises(r.Denied):
                r.validate_issue(e)
        e = exact_event()
        e["action"] = "edited"
        with self.assertRaises(r.Denied):
            r.validate_issue(e)
        e = exact_event()
        e["repository"]["full_name"] = "someone/else"
        with self.assertRaises(r.Denied):
            r.validate_issue(e)

    def test_live_issue_changed_or_receipted_cannot_execute(self):
        e = exact_event()
        with mock.patch.object(r.bridge, "_github_api", side_effect=[e["issue"], []]):
            self.assertEqual(r.checked_request(e, "token"), (407, f"/repos/{r.REPO}/issues/407"))
        prior = {"body": r.MARKER + "407 -->", "user": {"login": "github-actions[bot]"}}
        with mock.patch.object(r.bridge, "_github_api", side_effect=[e["issue"], [prior]]):
            with self.assertRaisesRegex(r.Denied, "ALREADY_RECEIPTED"):
                r.checked_request(e, "token")
        changed = {**e["issue"], "body": "tampered"}
        with mock.patch.object(r.bridge, "_github_api", return_value=changed):
            with self.assertRaisesRegex(r.Denied, "LIVE_ISSUE_MISMATCH"):
                r.checked_request(e, "token")

    def test_exact_plist_900s_only_release_path_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            releases = root / "releases"
            oldscript = releases / r.OLD / r.ENTRY
            oldscript.parent.mkdir(parents=True)
            oldscript.write_text("private-free-synthetic-fixture")
            plist = root / "klm.plist"
            base = {"Label": r.LABEL, "StartInterval": 900,
                    "ProgramArguments": ["/usr/bin/python3", str(oldscript), "--config", "fixture"],
                    "EnvironmentVariables": {"PYTHONPATH": str(releases / r.OLD / "src"),
                                             "PYTHONDONTWRITEBYTECODE": "1"}}
            original = plistlib.dumps(base)
            plist.write_bytes(original)
            a, b = r.old_plist_and_new(plist, releases)
            self.assertEqual(a, original)
            after = plistlib.loads(b)
            self.assertEqual(after["Label"], r.LABEL)
            self.assertEqual(after["StartInterval"], 900)
            self.assertEqual(after["ProgramArguments"],
                             [v.replace(r.OLD, r.NEW) for v in base["ProgramArguments"]])
            self.assertEqual(after["EnvironmentVariables"]["PYTHONPATH"],
                             base["EnvironmentVariables"]["PYTHONPATH"].replace(r.OLD, r.NEW))
            self.assertEqual(plist.read_bytes(), original)
            for field, bad in (("Label", "wrong"), ("StartInterval", 20),
                               ("ProgramArguments", ["/bin/sh"]),
                               ("EnvironmentVariables", {"PYTHONPATH": "unrelated"})):
                conf = dict(base)
                conf[field] = bad
                plist.write_bytes(plistlib.dumps(conf))
                with self.subTest(field=field), self.assertRaises(r.Denied):
                    r.old_plist_and_new(plist, releases)

    def test_idempotent_already_installed_has_no_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            p = pathlib.Path(temp) / "agent.plist"
            rel = pathlib.Path(temp) / "releases"
            item = {"Label": r.LABEL, "StartInterval": 900,
                    "ProgramArguments": ["/usr/bin/python3", str(rel / r.NEW / r.ENTRY)],
                    "EnvironmentVariables": {"PYTHONPATH": str(rel / r.NEW / "src")}}
            p.write_bytes(plistlib.dumps(item))
            self.assertTrue(r.is_new_plist(p, rel))
            item["StartInterval"] = 60
            p.write_bytes(plistlib.dumps(item))
            self.assertFalse(r.is_new_plist(p, rel))
            item["StartInterval"] = 900
            item["ProgramArguments"] = ["/bin/sh", "-c", "unexpected"]
            p.write_bytes(plistlib.dumps(item))
            self.assertFalse(r.is_new_plist(p, rel))

    def test_preflight_failure_does_not_start_service(self):
        with mock.patch.object(r, "owner_paths", return_value=(
                pathlib.Path("root"), pathlib.Path("plist"), pathlib.Path("releases"))), \
             mock.patch.object(r, "check_release"), \
             mock.patch.object(r, "is_new_plist", return_value=False), \
             mock.patch.object(r, "old_plist_and_new", return_value=(b"old", b"new")), \
             mock.patch.object(r, "stage"), \
             mock.patch.object(r, "compute_admission", side_effect=r.Denied("DEV_BUSY")), \
             mock.patch.object(r, "switch") as action:
            with self.assertRaisesRegex(r.Denied, "DEV_BUSY"):
                r.apply_once()
            action.assert_not_called()

    def test_bootstrap_failure_restores_old_exact_plist(self):
        with tempfile.TemporaryDirectory() as temp:
            p = pathlib.Path(temp) / "agent.plist"
            p.write_bytes(b"old-exact-plist-bytes")
            release = pathlib.Path(temp) / "release"
            release.mkdir()
            attempts = [0]
            def result(*args):
                value = mock.Mock(returncode=0, stdout="")
                if args[0] == "bootstrap":
                    value.returncode = 1 if attempts[0] == 0 else 0
                    attempts[0] += 1
                return value
            with mock.patch.object(r, "label_idle", return_value=True), \
                 mock.patch.object(r, "launch", side_effect=result):
                with self.assertRaisesRegex(r.Denied, "KLM_BOOTSTRAP_NEW_FAILED"):
                    r.switch(p, b"old-exact-plist-bytes", b"new", release)
            self.assertEqual(p.read_bytes(), b"old-exact-plist-bytes")
            self.assertEqual((release / "previous-klm-launchagent.plist").read_bytes(),
                             b"old-exact-plist-bytes")

    def test_canonical_source_blob_and_sha_required(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            for path in (r.ENTRY, r.HANDLER):
                (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / r.ENTRY).write_bytes(b"script")
            (root / r.HANDLER).write_bytes(b"handler")
            with mock.patch.object(r, "OLD_ENTRY_BLOB", r.blob(b"script")), \
                 mock.patch.object(r.subprocess, "run") as command:
                command.return_value.returncode = 0
                command.return_value.stdout = r.OLD + "\n"
                r.check_release(root, r.OLD, r.blob(b"handler"))
                (root / r.HANDLER).write_bytes(b"unauthorized")
                with self.assertRaisesRegex(r.Denied, "FINGERPRINT_MISMATCH"):
                    r.check_release(root, r.OLD, r.blob(b"handler"))

    def test_new_lifecycle_release_rejects_missing_modules(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            for path, data in ((r.ENTRY, b"script"), (r.HANDLER, b"handler")):
                p = root / path
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
            with mock.patch.object(r, "NEW_ENTRY_BLOB", r.blob(b"script")):
                with self.assertRaisesRegex(r.Denied, "LIFECYCLE_SOURCE_FINGERPRINT_MISMATCH"):
                    r.check_release(root, r.NEW, r.blob(b"handler"))


if __name__ == "__main__":
    unittest.main()
