"""No-model host-entrypoint acceptance for Harness -> reviewed GitHub child."""
import base64
import copy
import hashlib
import json
import os
from unittest.mock import patch
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import harness_decomposition_runtime as runtime
from ai_foundation.development_harness_roles import propose_decomposition
from local9b_issue_bridge import issue_task as existing_9b_issue_task

MAIN_SHA = "a" * 40
TEST_SOURCE = b"def test_fixture():\n    assert True\n"
TEST_HASH = hashlib.sha256(TEST_SOURCE).hexdigest()
SCOPES = {
    "src/ai_foundation/alpha.py": {
        "test": "tests/test_alpha.py", "test_sha256": TEST_HASH,
        "instruction": "Repair this independently verified red test."},
    "src/ai_foundation/beta.py": {
        "test": "tests/test_beta.py", "test_sha256": TEST_HASH,
        "instruction": "Repair this independently verified red test."},
}


def fixture_config():
    return {
        "schema": runtime.SCHEMA, "repository": runtime.REPO,
        "parent_issue": 70, "base_sha": MAIN_SHA,
        "reviewed_contracts": copy.deepcopy(SCOPES),
        "harness": {},
    }


def parent():
    return {
        "number": 70, "state": "open",
        "labels": [{"name": "foundation-autodev:ready"}],
        "body": "<!-- foundation-autodev: "
                + json.dumps({"paths": sorted(SCOPES), "depends_on": []}) + " -->",
    }


class API:
    def __init__(self):
        self.issues = [parent()]
        self.posted = []
        self.main_sha = MAIN_SHA
        self.branch_sha = MAIN_SHA
        self.test_contents = TEST_SOURCE
        self.requests = []

    def repo_path(self, suffix):
        return "/repos/" + runtime.REPO + suffix

    def request(self, path, method="GET", payload=None):
        self.requests.append((path, method))
        if path.endswith("/commits/main"):
            return {"sha": self.main_sha}
        if path.endswith("/commits/local9b%2Fharness-fixed-scope"):
            return {"sha": self.branch_sha}
        if "/contents/" in path:
            name = path.split("/contents/", 1)[1].split("?ref=", 1)[0]
            if name in SCOPES:
                return {"path": name, "type": "file", "sha": "a" * 40}
            if name in [x["test"] for x in SCOPES.values()]:
                return {"path": name, "type": "file", "encoding": "base64",
                        "content": base64.b64encode(self.test_contents).decode()}
            raise AssertionError(path)
        if path.endswith("/issues") and method == "POST":
            assert set(payload) == {"title", "body"}
            self.posted.append(payload)
            issue = {
                "number": 70 + len(self.posted),
                "state": "open", "title": payload["title"],
                "body": payload["body"], "labels": [],
            }
            self.issues.append(issue)
            return {"number": issue["number"]}
        if path.endswith("/labels") and method == "POST":
            number = int(path.rsplit("/", 2)[1])
            assert payload == {"labels": ["foundation-autodev:ready"]}
            child = next(x for x in self.issues if x["number"] == number)
            assert child["number"] != 70
            child["labels"].append({"name": "foundation-autodev:ready"})
            return copy.deepcopy(child["labels"])
        if "/issues?state=all" in path:
            return copy.deepcopy(self.issues)
        if "/issues/" in path:
            number = int(path.rsplit("/", 1)[1])
            return copy.deepcopy(next(x for x in self.issues
                                      if x["number"] == number))
        raise AssertionError((path, method))


class Role:
    def __init__(self):
        self.calls = []

    def invoke(self, role, prompt):
        self.calls.append((role, json.loads(prompt)))
        return json.dumps({
            "steps": [
                {"id": "s1", "target": "src/ai_foundation/alpha.py",
                 "purpose": "Repair bounded source alpha", "depends_on": []},
                {"id": "s2", "target": "src/ai_foundation/beta.py",
                 "purpose": "Repair bounded source beta", "depends_on": ["s1"]},
            ]
        })


class HostRuntimeTests(unittest.TestCase):
    def test_preview_validates_real_base_and_test_bytes_without_issues_write(self):
        api, model, config = API(), Role(), fixture_config()
        result = runtime.run_one(config, api, model)
        self.assertEqual(result["status"], "PREVIEW_ONLY")
        self.assertFalse(result["execution_authorized"])
        self.assertEqual([r["status"] for r in result["children"]],
                         ["CANDIDATE_NOT_AUTHORIZED", "WAITING_CHILD_ISSUE_IDS"])
        self.assertEqual(api.posted, [])
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(model.calls[0][0], "decomposition")
        self.assertEqual(model.calls[0][1]["host_write_targets"],
                         sorted(SCOPES))
        self.assertEqual(model.calls[0][1]["host_fixed_instructions"],
                         {key: pins["instruction"] for key, pins in SCOPES.items()})
        self.assertNotIn("GITHUB_TOKEN", json.dumps(model.calls))

    def test_only_actual_decomposition_inference_holds_existing_host_lease(self):
        api, model, config = API(), Role(), fixture_config()
        events = []
        class Lease:
            from contextlib import contextmanager
            @contextmanager
            def hold(self):
                events.append("acquire")
                try:
                    yield
                finally:
                    events.append("release")
        result = runtime.run_one(config, api, model, lease=Lease())
        self.assertEqual(result["status"], "PREVIEW_ONLY")
        self.assertEqual(events, ["acquire", "release"])
        events.clear()
        scope = {key: pin["test"] for key, pin in SCOPES.items()}
        frozen = propose_decomposition(model, issue_number=70,
                                       base_sha=MAIN_SHA, reviewed_scope=scope)
        model.calls.clear()
        result = runtime.run_one(config, api, model, publish=True,
                                 proposal_receipt=frozen, lease=Lease())
        self.assertEqual(result["status"], "CHILD_ISSUE_CREATED_UNAPPROVED")
        self.assertEqual(events, [])
        self.assertEqual(model.calls, [])

    def test_publisher_produces_one_unapproved_child_per_invocation(self):
        api, model, config = API(), Role(), fixture_config()
        frozen = propose_decomposition(
            model, issue_number=70, base_sha=MAIN_SHA,
            reviewed_scope={key: pin["test"] for key, pin in SCOPES.items()})
        a = runtime.run_one(config, api, model, publish=True,
                            proposal_receipt=frozen)
        self.assertEqual(a["status"], "CHILD_ISSUE_CREATED_UNAPPROVED")
        self.assertEqual(a["issue_number"], 71)
        self.assertEqual(api.issues[-1]["labels"], [])
        # Next call consumes the independently observed first child Issue ID.
        b = runtime.run_one(config, api, model, publish=True,
                            proposal_receipt=frozen)
        self.assertEqual(b["issue_number"], 72)
        self.assertIn('"depends_on":[71]', api.issues[-1]["body"])
        c = runtime.run_one(config, api, model, publish=True,
                            proposal_receipt=frozen)
        self.assertEqual(c["status"], "NO_CHILD_CREATION")
        self.assertEqual(len(api.posted), 2)

    def test_changed_model_plan_cannot_duplicate_existing_parent_children(self):
        api, model, config = API(), Role(), fixture_config()
        scope = {key: pin["test"] for key, pin in SCOPES.items()}
        frozen = propose_decomposition(model, issue_number=70, base_sha=MAIN_SHA,
                                       reviewed_scope=scope)
        runtime.run_one(config, api, model, publish=True,
                        proposal_receipt=frozen)
        first_count = len(api.posted)
        original = model.invoke
        def changed(role, prompt):
            plan = json.loads(original(role, prompt))
            plan["steps"][0]["purpose"] = "Completely revised interpretation"
            return json.dumps(plan)
        model.invoke = changed
        other = propose_decomposition(model, issue_number=70, base_sha=MAIN_SHA,
                                      reviewed_scope=scope)
        with self.assertRaisesRegex(ValueError, "CHILD_PARENT_PLAN_DRIFT"):
            runtime.run_one(config, api, model, publish=True,
                            proposal_receipt=other)
        self.assertEqual(len(api.posted), first_count)

    def test_edited_child_provenance_cannot_cause_duplicate_issue(self):
        api, model, config = API(), Role(), fixture_config()
        frozen = propose_decomposition(
            model, issue_number=70, base_sha=MAIN_SHA,
            reviewed_scope={key: pin["test"] for key, pin in SCOPES.items()})
        runtime.run_one(config, api, model, publish=True,
                        proposal_receipt=frozen)
        api.issues[-1]["body"] = api.issues[-1]["body"].replace(
            "<!-- foundation-harness-child:v1 ", "<!-- altered-child:v1 ")
        with self.assertRaisesRegex(ValueError, "CHILD_SEARCH_PROVENANCE_MISSING"):
            runtime.run_one(config, api, model, publish=True,
                            proposal_receipt=frozen)
        self.assertEqual(len(api.posted), 1)

    def test_parent_approved_independent_child_admits_into_existing_worker_once(self):
        api, model, config = API(), Role(), fixture_config()
        frozen = propose_decomposition(
            model, issue_number=70, base_sha=MAIN_SHA,
            reviewed_scope={key: pin["test"] for key, pin in SCOPES.items()})
        a = runtime.run_one(config, api, model, publish=True,
                            proposal_receipt=frozen)
        b = runtime.run_one(config, api, model, publish=True,
                            proposal_receipt=frozen)
        self.assertEqual((a["issue_number"], b["issue_number"]), (71, 72))
        model.calls.clear()

        approved = runtime.run_one(
            config, api, model, admit=True, proposal_receipt=frozen)
        self.assertEqual(approved["status"],
                         "INDEPENDENT_CHILD_READY_FOR_EXISTING_WORKER")
        self.assertEqual(approved["issue_number"], 71)
        self.assertEqual(approved["authority_source"],
                         "EXACT_READY_PARENT_AND_PINNED_HOST_CONTRACT")
        self.assertEqual(model.calls, [])
        self.assertEqual(len(api.posted), 2)
        self.assertIn({"name": "foundation-autodev:ready"},
                      api.issues[1]["labels"])
        # The *existing* 9B parser, not a new one, can consume this exact
        # approved independent child without model-generated instructions.
        actual_worker_issue = copy.deepcopy(api.issues[1])
        actual_worker_issue["state"] = "OPEN"
        actual_worker_issue["updatedAt"] = "2026-11-10T01:00:00Z"
        admitted_contract = existing_9b_issue_task(actual_worker_issue)
        self.assertEqual(admitted_contract["recipe"], "python-fixed-test")
        self.assertEqual(admitted_contract["target"],
                         "src/ai_foundation/alpha.py")
        self.assertEqual(admitted_contract["test_sha256"], TEST_HASH)
        self.assertEqual(admitted_contract["base_sha"], MAIN_SHA)
        # A dependent child is NOT runnable against the unmerged same base.
        self.assertEqual(api.issues[2]["labels"], [])
        again = runtime.run_one(
            config, api, model, admit=True, proposal_receipt=frozen)
        self.assertEqual(again["status"], "NO_INDEPENDENT_CHILD_TO_ADMIT")
        self.assertEqual(api.issues[2]["labels"], [])

    def test_child_admission_requires_parent_and_test_pin_still_current(self):
        api, model, config = API(), Role(), fixture_config()
        frozen = propose_decomposition(
            model, issue_number=70, base_sha=MAIN_SHA,
            reviewed_scope={key: pin["test"] for key, pin in SCOPES.items()})
        runtime.run_one(config, api, model, publish=True,
                        proposal_receipt=frozen)
        api.issues[0]["labels"].append({"name": "foundation-autodev:hold"})
        with self.assertRaisesRegex(ValueError, "HOST_PARENT_NOT_APPROVED"):
            runtime.run_one(config, api, model, admit=True, proposal_receipt=frozen)
        self.assertEqual(api.issues[1]["labels"], [])
        api.issues[0]["labels"] = [{"name": "foundation-autodev:ready"}]
        api.test_contents = b"invalid fixed test bytes"
        with self.assertRaisesRegex(ValueError, "HOST_FIXED_TEST_SHA_DRIFT"):
            runtime.run_one(config, api, model, admit=True, proposal_receipt=frozen)
        self.assertEqual(api.issues[1]["labels"], [])

    def test_existing_9b_branch_stays_pinned_despite_unrelated_main_changes(self):
        api, model, config = API(), Role(), fixture_config()
        config["base"] = "local9b/harness-fixed-scope"
        # Unrelated main updates must not invalidate the reviewed immutable
        # source/test branch's fixed SHA.
        api.main_sha = "b" * 40
        preview = runtime.run_one(config, api, model)
        self.assertEqual(preview["status"], "PREVIEW_ONLY")
        self.assertNotIn(("/repos/" + runtime.REPO + "/commits/main", "GET"),
                         api.requests)
        frozen = propose_decomposition(
            model, issue_number=70, base_sha=MAIN_SHA,
            reviewed_scope={key: pin["test"] for key, pin in SCOPES.items()})
        runtime.run_one(config, api, model, publish=True,
                        proposal_receipt=frozen)
        runtime.run_one(config, api, model, admit=True,
                        proposal_receipt=frozen)
        child = copy.deepcopy(api.issues[1])
        child["state"] = "OPEN"
        child["updatedAt"] = "2026-11-10T01:00:00Z"
        accepted = existing_9b_issue_task(child)
        self.assertEqual(accepted["base"], config["base"])
        self.assertEqual(accepted["base_sha"], MAIN_SHA)
        self.assertEqual(accepted["test_sha256"], TEST_HASH)
        api.branch_sha = "c" * 40
        with self.assertRaisesRegex(ValueError, "HOST_BASE_SHA_MOVED"):
            runtime.run_one(config, api, model, admit=True,
                            proposal_receipt=frozen)

    def test_bad_test_hash_and_moved_main_abort_before_model(self):
        api, model, config = API(), Role(), fixture_config()
        api.main_sha = "b" * 40
        with self.assertRaisesRegex(ValueError, "HOST_BASE_SHA_MOVED"):
            runtime.run_one(config, api, model, publish=True)
        self.assertEqual(model.calls, [])
        self.assertEqual(api.posted, [])
        api.main_sha = MAIN_SHA
        api.test_contents = b"edited immutable acceptance"
        with self.assertRaisesRegex(ValueError, "HOST_FIXED_TEST_SHA_DRIFT"):
            runtime.run_one(config, api, model, publish=True)
        self.assertEqual(model.calls, [])
        self.assertEqual(api.posted, [])

    def test_preflight_requires_current_ready_parent_before_model(self):
        api, model, config = API(), Role(), fixture_config()
        contracts = runtime.verify_host_baseline(api, config)
        check = runtime.verify_parent_scope(api, config, contracts)
        self.assertEqual(check["status"], "PRE_MODEL_VERIFIED")
        self.assertEqual(check["reviewed_targets"], 2)
        self.assertIs(check["execution_authorized"], False)
        self.assertEqual(model.calls, [])
        api.issues[0]["labels"] = [{"name": "foundation-autodev:hold"}]
        with self.assertRaisesRegex(ValueError, "HOST_PARENT_NOT_APPROVED"):
            runtime.run_one(config, api, model)
        self.assertEqual(model.calls, [])
        api.issues[0]["labels"] = [{"name": "foundation-autodev:ready"}]
        api.issues[0]["body"] = '<!-- foundation-autodev: {"paths":["src/other.py"]} -->'
        with self.assertRaisesRegex(ValueError, "HOST_PARENT_SCOPE_INVALID"):
            runtime.run_one(config, api, model)
        self.assertEqual(model.calls, [])

    def test_bad_parent_after_model_or_revised_plan_prevents_new_child(self):
        api, model, config = API(), Role(), fixture_config()
        # The model step itself may take time. Parent withdrawal during it
        # is refused by the post-inference Issue readback.
        original = model.invoke
        def revoked(role, prompt):
            api.issues[0]["labels"] = [{"name": "foundation-autodev:hold"}]
            return original(role, prompt)
        model.invoke = revoked
        with self.assertRaisesRegex(ValueError, "PARENT_ISSUE_NOT_APPROVED"):
            runtime.run_one(config, api, model)
        self.assertEqual(api.posted, [])

    def test_frozen_plan_receipt_is_immutable_and_skips_second_model_call(self):
        api, model, config = API(), Role(), fixture_config()
        with tempfile.TemporaryDirectory() as temp:
            host = Path(temp) / "owner.json"
            host.write_text("owner bound")
            host.chmod(0o600)
            saved = Path(temp) / "plan.json"
            staged = runtime.run_one(
                config, api, model, stage_plan_file=str(saved),
                owner_config_path=str(host))
            self.assertEqual(staged["status"], "PLAN_STAGED")
            self.assertTrue(saved.is_file())
            self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
            receipt = runtime._load_plan_receipt(
                str(saved), staged["plan_file_sha256"])
            self.assertEqual(staged["proposal_sha256"], receipt["proposal_sha256"])
            call_count = len(model.calls)
            first = runtime.run_one(config, api, model, publish=True,
                                    proposal_receipt=receipt)
            self.assertEqual(first["status"], "CHILD_ISSUE_CREATED_UNAPPROVED")
            self.assertEqual(len(model.calls), call_count)
            with self.assertRaisesRegex(ValueError, "HOST_PLAN_RECEIPT_PATH_INVALID"):
                runtime.run_one(config, api, model, stage_plan_file=str(saved),
                                owner_config_path=str(host))
            saved.write_text(saved.read_text() + " ")
            with self.assertRaisesRegex(ValueError, "HOST_FILE_BYTES_DRIFT"):
                runtime._load_plan_receipt(
                    str(saved), staged["plan_file_sha256"])

    def test_publication_without_frozen_plan_fails_before_effect(self):
        api, model, config = API(), Role(), fixture_config()
        with self.assertRaisesRegex(ValueError, "PUBLISH_REQUIRES_FROZEN_PROPOSAL"):
            runtime.run_one(config, api, model, publish=True)
        self.assertEqual(api.posted, [])
        self.assertEqual(model.calls, [])

    def test_harness_environment_has_no_github_or_cloud_credentials(self):
        with patch.dict(os.environ, {
            "GITHUB_TOKEN": "never-into-model",
            "OPENAI_API_KEY": "never-into-model",
            "GROQ_API_KEY": "never-into-model",
            "DSH_HOME": "/shared/cloud-config",
            "HOME": "/shared/cloud-config",
            "OLLAMA_HOST": "127.0.0.1:11436",
            "OLLAMA_API_KEY": "local-placeholder",
        }, clear=True):
            env = runtime._safe_inference_env("/private/harness")
            self.assertEqual(env["DSH_HOME"], "/private/harness")
            self.assertEqual(env["HOME"], "/private/harness")
            self.assertNotIn("GITHUB_TOKEN", env)
            self.assertNotIn("OPENAI_API_KEY", env)
            self.assertNotIn("GROQ_API_KEY", env)
            self.assertEqual(env["OLLAMA_HOST"], "127.0.0.1:11436")
        with patch.dict(os.environ, {"OLLAMA_HOST": "http://paid.example.com:443"},
                        clear=True):
            with self.assertRaisesRegex(ValueError, "HARNESS_NONLOCAL_OLLAMA_HOST"):
                runtime._safe_inference_env("/private/harness")

    def test_host_config_pin_exact_argv_and_no_world_writable_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            seatbelt = root / "guard.sb"
            overlay = root / "role.patch.yml"
            dsh = root / "dsh"
            for obj, data in ((seatbelt, "(version 1)\n"),
                              (overlay, "provider: local\n"),
                              (dsh, "stub\n")):
                obj.write_text(data)
                obj.chmod(0o600)
            config = fixture_config()
            config["harness"] = {
                "argv": ["/usr/bin/sandbox-exec", "-f", str(seatbelt),
                         str(dsh), "--profile", "headless", "--patch", str(overlay)],
                "cwd": temp, "timeout_s": 90,
                "seatbelt_sha256": hashlib.sha256(seatbelt.read_bytes()).hexdigest(),
                "patch_sha256": hashlib.sha256(overlay.read_bytes()).hexdigest(),
            }
            saved = root / "approved.json"
            saved.write_text(json.dumps(config))
            saved.chmod(0o600)
            sha = hashlib.sha256(saved.read_bytes()).hexdigest()
            self.assertEqual(runtime.load_host_config(str(saved), sha), config)
            config["base"] = "local9b/harness-fixed-scope"
            saved.write_text(json.dumps(config))
            sha = hashlib.sha256(saved.read_bytes()).hexdigest()
            self.assertEqual(runtime.load_host_config(str(saved), sha), config)
            config["base"] = "local9b/../escape"
            saved.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, "HOST_BASE_BRANCH_INVALID"):
                runtime.load_host_config(
                    str(saved), hashlib.sha256(saved.read_bytes()).hexdigest())
            config["base"] = "local9b/harness-fixed-scope"
            saved.write_text(json.dumps(config))
            sha = hashlib.sha256(saved.read_bytes()).hexdigest()
            # A digest mismatch prevents every downstream tool call.
            saved.write_text(saved.read_text() + " ")
            with self.assertRaisesRegex(ValueError, "HOST_FILE_BYTES_DRIFT"):
                runtime.load_host_config(str(saved), sha)
            saved.chmod(0o666)
            with self.assertRaisesRegex(ValueError, "HOST_FILE_MODE_OR_SIZE_INVALID"):
                runtime.load_host_config(
                    str(saved), hashlib.sha256(saved.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
