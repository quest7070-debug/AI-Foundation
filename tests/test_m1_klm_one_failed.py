"""No real Drive, M1, source contents or model calls; fixed recovery acceptance."""
import json
import pathlib
import sqlite3
import tempfile
import unittest
from unittest import mock
from scripts import m1_klm_one_failed as r


def ev():
    return {"action":"opened","repository":{"full_name":r.REPO},
            "issue":{"number":412,"state":"open","title":r.TITLE,
                     "body":r.BODY,"user":{"login":r.OWNER}}}


class OneFailedContractTests(unittest.TestCase):
    def test_authorized_issue_exact_owner_repo_body_only(self):
        self.assertEqual(r.validate_issue(ev()),412)
        for change in ({"state":"closed"},{"user":{"login":"other"}},
                       {"body":r.BODY+" another command"},{"title":"shell"},
                       {"number":True}):
            event=ev()
            event["issue"].update(change)
            with self.subTest(change=change), self.assertRaises(r.Denied):
                r.validate_issue(event)
        for key,value in (("action","edited"),("repository",{"full_name":"other/repo"})):
            event=ev();event[key]=value
            with self.assertRaises(r.Denied):r.validate_issue(event)

    def test_changed_live_issue_and_duplicate_receipt_rejected(self):
        e=ev()
        with mock.patch.object(r.bridge,"_github_api",side_effect=[e["issue"],[]]):
            self.assertEqual(r.live_request(e,"token")[0],412)
        with mock.patch.object(r.bridge,"_github_api",side_effect=[
            {**e["issue"],"body":"edited"}]):
            with self.assertRaisesRegex(r.Denied,"CHANGED"):
                r.live_request(e,"token")
        receipt={"user":{"login":"github-actions[bot]"},
                 "body":r.MARKER+"412 -->"}
        with mock.patch.object(r.bridge,"_github_api",side_effect=[e["issue"],[receipt]]):
            with self.assertRaisesRegex(r.Denied,"ALREADY_RECEIPTED"):
                r.live_request(e,"token")

    def test_pinned_source_git_blob_id(self):
        self.assertEqual(r.gitblob(b"hello"),
                         "b6fc4c620b67d95f953a5c1c1230aaab5db5a1b0")
        self.assertEqual(r.SHA,"369e74a4f8a9f19f369aa182f865b2d8fadb57c0")
        self.assertEqual(set(r.BLOBS),{
            "scripts/klm_drive_host_tick.py",
            "src/ai_foundation/klm_9b_handler.py",
            "src/ai_foundation/knowledge_lifecycle.py",
            "src/ai_foundation/klm_drive_cycle.py",
            "src/ai_foundation/klm_drive_work.py",
            "src/ai_foundation/klm_projection.py"})

    def test_read_only_metrics_expose_no_private_rows_or_text(self):
        with tempfile.TemporaryDirectory() as td:
            db=pathlib.Path(td)/"work.db"
            con=sqlite3.connect(db)
            con.execute("CREATE TABLE work_steps(job_id TEXT,position INTEGER,name TEXT,status TEXT,result TEXT)")
            con.execute("CREATE TABLE klm_drive_intake(job_id TEXT, private_text TEXT)")
            for i, status in enumerate(["FAILED","FAILED","VERIFIED","PLANNED"]):
                con.execute("INSERT INTO work_steps VALUES(?,0,'klm-readonly',?,?)",
                            (str(i),status,"SECRET PERSON SOURCE"))
                con.execute("INSERT INTO klm_drive_intake VALUES(?,?)",
                            (str(i),"SECRET PERSON SOURCE"))
            con.execute("CREATE TABLE klm_atoms(atom_id TEXT)")
            con.execute("INSERT INTO klm_atoms VALUES('fixture')")
            con.commit();con.close()
            result=r.read_counts(db)
            self.assertEqual(result["work_states"]["FAILED"],2)
            self.assertEqual(result["work_states"]["VERIFIED"],1)
            self.assertEqual(result["atoms"],1)
            self.assertIsNone(result["relations"])
            self.assertEqual(result["audits_verified"],0)
            self.assertNotIn("SECRET PERSON SOURCE",str(result))

    def test_unknown_work_status_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            db=pathlib.Path(td)/"work.db"
            con=sqlite3.connect(db)
            con.execute("CREATE TABLE work_steps(job_id TEXT,position INTEGER,name TEXT,status TEXT)")
            con.execute("CREATE TABLE klm_drive_intake(job_id TEXT)")
            con.execute("INSERT INTO work_steps VALUES('1',0,'klm-readonly','DANGEROUS')")
            con.execute("INSERT INTO klm_drive_intake VALUES('1')")
            con.commit();con.close()
            with self.assertRaisesRegex(r.Denied,"STATE_UNTRUSTED"):
                r.read_counts(db)

    def test_busy_compute_fail_closed_when_other_worker_present(self):
        with mock.patch.object(r.subprocess,"run") as run:
            run.return_value.returncode=0
            run.return_value.stdout="/usr/bin/Runner.Worker\n/usr/bin/Runner.Worker\n"
            self.assertFalse(r.compute_idle())
            run.return_value.stdout="/usr/bin/Runner.Worker\n/usr/bin/llama-server\n"
            self.assertFalse(r.compute_idle())

    def test_preflight_records_run_id_without_accessing_source(self):
        e=ev()
        with mock.patch.dict(r.os.environ,{
            "GITHUB_REPOSITORY":r.REPO,
            "GITHUB_EVENT_NAME":"issues",
            "GITHUB_WORKFLOW":r.WORKFLOW,
            "GITHUB_EVENT_PATH":"/fixture/event.json",
            "GITHUB_TOKEN":"FIXTURE_TOKEN",
            "GITHUB_RUN_ID":"987654",
        }), mock.patch.object(r.Path,"read_text",return_value=json.dumps(e)), \
             mock.patch.object(r,"live_request",return_value=(412,"/repos/"+r.REPO+"/issues/412")), \
             mock.patch.object(r,"one_failed") as effect, \
             mock.patch.object(r.bridge,"_github_api") as api, \
             mock.patch.object(r.sys,"argv",["klm","--preflight"]):
            r.main()
            effect.assert_not_called()
            body=api.call_args.args[3]["body"]
            self.assertIn("987654",body)
            self.assertIn("foundation-klm-recovery-start:v1:412",body)
            self.assertNotIn("FIXTURE_TOKEN",body)

    def test_denial_never_prints_exception_details_to_receipt(self):
        e=ev()
        with mock.patch.dict(r.os.environ,{
            "GITHUB_REPOSITORY":r.REPO,
            "GITHUB_EVENT_NAME":"issues",
            "GITHUB_WORKFLOW":r.WORKFLOW,
            "GITHUB_EVENT_PATH":"/fixture/event.json",
            "GITHUB_TOKEN":"FIXTURE_TOKEN",
            "GITHUB_RUN_ID":"12345",
        }), mock.patch.object(r.Path,"read_text",return_value=json.dumps(e)), \
             mock.patch.object(r,"live_request",return_value=(412,"/repos/"+r.REPO+"/issues/412")), \
             mock.patch.object(r,"one_failed",side_effect=RuntimeError("private/person/name")), \
             mock.patch.object(r.bridge,"_github_api") as api, \
             mock.patch.object(r.sys,"argv",["klm"]):
            with self.assertRaises(SystemExit):
                r.main()
            receipt=api.call_args.args[3]
            self.assertIn("KLM_UNEXPECTED_RuntimeError",receipt["body"])
            self.assertNotIn("private/person/name",receipt["body"])

if __name__=="__main__":
    unittest.main()
