"""Model-free handoff tests: scoped parent -> GitHub Issue -> 9B admission."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from ai_foundation.development_harness_roles import propose_decomposition
import harness_decomposition_issue_bridge as handoff
import local9b_issue_bridge as worker
from github_task_orchestrator import metadata, build_plan


def fixtures(dependent=True):
    rows = [
        {"id": "s1", "target": "src/ai_foundation/alpha.py",
         "purpose": "Fix the alpha source", "depends_on": []},
        {"id": "s2", "target": "src/ai_foundation/beta.py",
         "purpose": "Fix the beta source", "depends_on": ["s1"] if dependent else []},
    ]
    class Snapshot:
        def invoke(self, role, instruction):
            assert role == "decomposition"
            return json.dumps({"steps": rows})
    scope = {
        "src/ai_foundation/alpha.py": "tests/test_alpha.py",
        "src/ai_foundation/beta.py": "tests/test_beta.py",
    }
    proposal = propose_decomposition(Snapshot(), issue_number=70,
                                      base_sha="a" * 40, reviewed_scope=scope)
    parent = {
        "number": 70, "state": "open",
        "labels": [{"name": "foundation-autodev:ready"}],
        "body": "<!-- foundation-autodev: " +
                json.dumps({"paths": sorted(scope), "depends_on": []}) + " -->",
    }
    pinned = {
        source: {"test": test, "test_sha256": "b" * 64,
                 "instruction": "Fix this host-proven test failure."}
        for source, test in scope.items()
    }
    return proposal, parent, pinned


class IssueHandoffTests(unittest.TestCase):
    def handoff(self, proposal=None, parent=None, pins=None, children=None):
        proposal0, parent0, pins0 = fixtures()
        return handoff.child_issue_candidates(
            proposal=proposal if proposal is not None else proposal0,
            current_parent=parent if parent is not None else parent0,
            reviewed_contracts=pins if pins is not None else pins0,
            existing_children=children)

    def test_harness_to_child_contract_rereads_parent_after_model(self):
        proposal, parent, pins = fixtures()
        observed = []
        class FrozenRoles:
            def invoke(self, role, prompt):
                observed.append("model")
                self.assert_role = role
                return json.dumps({"steps": [
                    {k: row[k] for k in ("id", "target", "purpose", "depends_on")}
                    for row in proposal["steps"]]})
        roles = FrozenRoles()
        def fresh_parent(issue_no):
            observed.append("parent")
            self.assertEqual(issue_no, 70)
            return parent
        def fresh_children(issue_no, plan_digest):
            observed.append("children")
            self.assertEqual(issue_no, 70)
            self.assertEqual(plan_digest, proposal["proposal_sha256"])
            return {}
        result = handoff.propose_child_issue_candidates(
            roles=roles, parent_issue_number=70, base_sha="a" * 40,
            reviewed_contracts=pins,
            read_current_parent=fresh_parent,
            read_existing_children=fresh_children)
        self.assertEqual(observed, ["model", "parent", "children"])
        self.assertEqual(result["children"][0]["status"], "CANDIDATE_NOT_AUTHORIZED")
        self.assertEqual(roles.assert_role, "decomposition")
        def revoked(_):
            altered = copy.deepcopy(parent)
            altered["labels"] = [{"name": "foundation-autodev:hold"}]
            return altered
        with self.assertRaisesRegex(ValueError, "PARENT_ISSUE_NOT_APPROVED"):
            handoff.propose_child_issue_candidates(
                roles=roles, parent_issue_number=70, base_sha="a" * 40,
                reviewed_contracts=pins,
                read_current_parent=revoked,
                read_existing_children=fresh_children)

    def test_first_child_contract_matches_existing_issue_parser(self):
        result = self.handoff()
        self.assertIs(result["execution_authorized"], False)
        children = result["children"]
        self.assertEqual([x["status"] for x in children],
                         ["CANDIDATE_NOT_AUTHORIZED", "WAITING_CHILD_ISSUE_IDS"])
        self.assertEqual(children[0]["labels"], [])
        self.assertIn("foundation-autodev-task", children[0]["body"])
        self.assertEqual(children[1]["waiting_for"], ["s1"])
        names, deps = metadata(children[0]["body"], 71)
        self.assertEqual(names, ["src/ai_foundation/alpha.py"])
        self.assertEqual(deps, [])
        child = {
            "number": 71, "state": "OPEN", "updatedAt": "2026-11-10T00:00:00Z",
            "labels": [{"name": worker.READY_LABEL}],
            "body": children[0]["body"],
        }
        task = worker.issue_task(child)
        self.assertEqual(task["recipe"], "python-fixed-test")
        self.assertEqual(task["target"], "src/ai_foundation/alpha.py")
        self.assertEqual(task["test_sha256"], "b" * 64)
        self.assertEqual(task["base_sha"], "a" * 40)

    def test_child_dependencies_are_real_readback_issue_numbers(self):
        initial = self.handoff()
        original = initial["children"][0]
        existing = {"number": 71, "state": "open", "body": original["body"]}
        next_stage = self.handoff(children={"s1": existing})
        self.assertEqual(next_stage["children"][0]["status"], "EXISTING_CHILD")
        child2 = next_stage["children"][1]
        self.assertEqual(child2["status"], "CANDIDATE_NOT_AUTHORIZED")
        self.assertEqual(child2["depends_on_issues"], [71])
        names, deps = metadata(child2["body"], 72)
        self.assertEqual((names, deps),
                         (["src/ai_foundation/beta.py"], [71]))

        candidate = {"number": 72, "state": "OPEN",
                     "updatedAt": "2026-11-10T00:00:00Z",
                     "labels": [{"name": worker.READY_LABEL}],
                     "body": child2["body"]}
        with patch.object(worker, "_gh", return_value={"number": 71, "state": "OPEN"}):
            with self.assertRaisesRegex(ValueError, "TASK_DEPENDENCY_NOT_CLOSED"):
                worker.issue_task(candidate)
        with patch.object(worker, "_gh", return_value={"number": 71, "state": "CLOSED"}):
            task = worker.issue_task(candidate)
        self.assertEqual(task["target"], "src/ai_foundation/beta.py")

        state_open = {"number": 71, "state": "open", "labels": [],
                      "body": original["body"]}
        planned = build_plan("quest7070-dev/AI-Foundation", [state_open, {
            "number": 72, "state": "open",
            "labels": [{"name": worker.READY_LABEL}], "body": candidate["body"]}], [], [])
        self.assertEqual(len(planned["blocked_items"]), 1)

    def test_drift_hold_and_forged_child_are_refused(self):
        proposal, parent, pins = fixtures()
        frozen = copy.deepcopy(proposal)
        frozen["steps"][0]["target"] = "secrets/tokens.py"
        with self.assertRaises(ValueError):
            self.handoff(proposal=frozen, parent=parent, pins=pins)
        held = copy.deepcopy(parent)
        held["labels"].append({"name": "foundation-autodev:hold"})
        with self.assertRaisesRegex(ValueError, "PARENT_ISSUE_NOT_APPROVED"):
            self.handoff(proposal=proposal, parent=held, pins=pins)
        missing_label = copy.deepcopy(parent)
        missing_label["labels"] = []
        with self.assertRaisesRegex(ValueError, "PARENT_ISSUE_NOT_APPROVED"):
            self.handoff(proposal=proposal, parent=missing_label, pins=pins)
        bad_scope = copy.deepcopy(parent)
        bad_scope["body"] = '<!-- foundation-autodev: {"paths":["src/extra.py"]} -->'
        with self.assertRaisesRegex(ValueError, "PARENT_ISSUE_SCOPE_MISMATCH"):
            self.handoff(proposal=proposal, parent=bad_scope, pins=pins)

    def test_single_child_publisher_reuses_discovery_and_never_auto_ready(self):
        proposal, parent, pins = fixtures()
        created = []
        children = {}
        def get_parent(number):
            self.assertEqual(number, 70)
            return copy.deepcopy(parent)
        def list_children(number, digest):
            self.assertEqual((number, digest), (70, proposal["proposal_sha256"]))
            return copy.deepcopy(children)
        def create_issue(payload):
            self.assertEqual(set(payload), {"title", "body"})
            number = 71 + len(created)
            issue = {"number": number, "state": "open",
                     "labels": [], "body": payload["body"]}
            step_id = "s1" if number == 71 else "s2"
            created.append(payload)
            children[step_id] = issue
            return {"number": number}
        def read_issue(number):
            return next(copy.deepcopy(child) for child in children.values()
                        if child["number"] == number)
        def run():
            return handoff.publish_one_unapproved_child(
                proposal=proposal, reviewed_contracts=pins,
                read_current_parent=get_parent,
                read_existing_children=list_children,
                create_issue=create_issue,
                read_issue=read_issue)
        first = run()
        self.assertEqual(first["status"], "CHILD_ISSUE_CREATED_UNAPPROVED")
        self.assertEqual((first["step_id"], first["issue_number"]), ("s1", 71))
        second = run()
        self.assertEqual((second["step_id"], second["issue_number"]), ("s2", 72))
        self.assertEqual(metadata(created[1]["body"], 72)[1], [71])
        self.assertEqual(run()["status"], "NO_CHILD_CREATION")
        self.assertEqual(len(created), 2)
        self.assertFalse(first["execution_authorized"])
        self.assertFalse(second["execution_authorized"])

    def test_publisher_aborts_if_parent_changes_before_post(self):
        proposal, parent, pins = fixtures()
        calls = []
        def parent_changes(number):
            calls.append("read")
            issue = copy.deepcopy(parent)
            if len(calls) > 1:
                issue["labels"] = [{"name": "foundation-autodev:hold"}]
            return issue
        def never_post(_):
            raise AssertionError("creation must not occur after approval revoked")
        with self.assertRaisesRegex(ValueError, "CHILD_PUBLISH_READBACK_CHANGED"):
            handoff.publish_one_unapproved_child(
                proposal=proposal, reviewed_contracts=pins,
                read_current_parent=parent_changes,
                read_existing_children=lambda *_: {},
                create_issue=never_post,
                read_issue=lambda *_: None)

    def test_child_marker_rejects_edits_or_other_parent(self):
        first = self.handoff()["children"][0]
        tampered = {"number": 71, "state": "open", "body": first["body"] + "changed"}
        with self.assertRaisesRegex(ValueError, "CHILD_ISSUE_EDITED_AFTER_CREATION"):
            self.handoff(children={"s1": tampered})
        alien = {"number": 71, "state": "open",
                 "body": first["body"].replace('"parent_issue":70',
                                                '"parent_issue":999')}
        with self.assertRaisesRegex(ValueError, "CHILD_PROVENANCE_MISMATCH"):
            self.handoff(children={"s1": alien})
        pins = fixtures()[2]
        pins["src/ai_foundation/alpha.py"]["instruction"] = ""
        with self.assertRaisesRegex(ValueError, "PYTHON_TASK_INSTRUCTION_INVALID"):
            self.handoff(pins=pins)

    def test_real_github_adapter_discovers_closed_children_before_repost(self):
        proposal, parent, pins = fixtures()
        class API:
            def __init__(self):
                self.issues = [copy.deepcopy(parent)]
                self.posts = []
            def repo_path(self, suffix):
                return "/repos/test/repo" + suffix
            def request(self, path, method="GET", payload=None):
                if path.startswith("/repos/test/repo/issues?state=all"):
                    return copy.deepcopy(self.issues)
                if path == "/repos/test/repo/issues" and method == "POST":
                    self.assert_new_issue_payload = payload
                    assert set(payload) == {"title", "body"}
                    self.posts.append(payload)
                    created = {"number": 70 + len(self.posts),
                               "state": "open", "body": payload["body"],
                               "labels": []}
                    self.issues.append(created)
                    return {"number": created["number"]}
                if path.startswith("/repos/test/repo/issues/"):
                    number = int(path.rsplit("/", 1)[1])
                    return copy.deepcopy(next(x for x in self.issues
                                              if x["number"] == number))
                raise AssertionError((path, method))
        api = API()
        first = handoff.publish_next_child_from_github(
            api=api, proposal=proposal, reviewed_contracts=pins)
        self.assertEqual(first["issue_number"], 71)
        api.issues[-1]["state"] = "closed"
        second = handoff.publish_next_child_from_github(
            api=api, proposal=proposal, reviewed_contracts=pins)
        self.assertEqual(second["issue_number"], 72)
        self.assertEqual(metadata(api.issues[-1]["body"], 72)[1], [71])
        third = handoff.publish_next_child_from_github(
            api=api, proposal=proposal, reviewed_contracts=pins)
        self.assertEqual(third["status"], "NO_CHILD_CREATION")
        self.assertEqual(len(api.posts), 2)

    def test_scope_mismatch_does_not_enter_worker(self):
        original = self.handoff()["children"][0]
        child = {"number": 71, "state": "OPEN", "updatedAt": "rev",
                 "labels": [{"name": worker.READY_LABEL}],
                 "body": original["body"].replace(
                     '"paths":["src/ai_foundation/alpha.py"]',
                     '"paths":["src/ai_foundation/beta.py"]')}
        with self.assertRaisesRegex(ValueError, "TASK_DECLARED_WRITE_SCOPE_MISMATCH"):
            worker.issue_task(child)


if __name__ == "__main__":
    unittest.main()
