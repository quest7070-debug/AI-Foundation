"""Real disposable Guard/ledger/MCP correction path; no live owner or model."""
from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/human_model"))
from human_model_host_mcp import HumanModelOwnerMcpPort, TrustedOwnerSourcePort
from human_model_ledger import Ledger
from human_model_owner_publication import prepare_admission_schema
from human_model_source_admission import HostCollectionGrant, TrustedSourceSnapshot
from ai_foundation.core import CanonContract
from ai_foundation.guard import GuardCore
from ai_foundation.human_model_collection_guard import GuardCollectionConsent, collection_intent
from ai_foundation.human_model_context import HumanModelBinding
from ai_foundation.mcp_host import AuthenticatedMcpHost, McpHostAuthorizer
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.operator_server import OperatorApplication
from ai_foundation.productization import FoundationConfig
from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.primary_review_events import PrimaryReviewTransitions
from ai_foundation.store import SQLiteGuardStore, approval_request_ref
from scripts.foundation_mcp_stdio import BOUND_TOOLS, MCPStdio


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


class OwnerCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        runtime = root / "runtime"
        runtime.mkdir()
        config = FoundationConfig(str(runtime))
        self.store = SQLiteGuardStore(runtime / config.guard_db)
        self.guard = GuardCore(self.store.runtime_state(), store=self.store)
        self.binding = HumanModelBinding("owner@m1", str(root), "owner-view", ("work",), "private")
        self.canon = CanonContract("synthetic-correction", "canon-v1")
        self.task_id = "review-task"
        self.generation = digest("original-review-generation")
        self.answer_evidence = digest("original-answer-evidence")
        SQLiteWorkStore(runtime / config.work_db)
        reviews = PrimaryReviewTransitions(runtime / config.work_db)
        reviews.started(self.task_id, self.generation)
        reviews.resolved(self.task_id, self.generation,
                         "MATCHED_EXISTING_DELEGATION",
                         evidence_sha256=self.answer_evidence,
                         answer_text="synthetic answer")
        self.reviews = reviews
        self.consent = GuardCollectionConsent(authenticated_owner="owner@m1", binding=self.binding,
                                             guard=self.guard, canon=self.canon)
        self.path = root / "owner.sqlite"
        with closing(Ledger(self.path)) as ledger:
            prepare_admission_schema(ledger)
            ledger.define_view(view_id="owner-view", purpose="synthetic", audience="foundation",
                               allowed_scopes=["work"], max_privacy="private")
        self.grants, self.snapshots = {}, {}
        self.add_source("old", "ORIGINAL_PRIVATE_SOURCE")
        self.add_source("new", "CORRECTED_PRIVATE_SOURCE")
        self.permit_correction = True
        self.port = HumanModelOwnerMcpPort(
            binding=self.binding, consent=self.consent,
            open_owner_ledger=lambda: Ledger(self.path),
            open_readonly_connection=lambda: sqlite3.connect(self.path.as_uri()+"?mode=ro", uri=True),
            source=TrustedOwnerSourcePort(grant_for=self.grant_for,
                                         read_current=lambda system, record: self.snapshots[record]),
            authorize_correction=self.correction_authority,
            open_review_readonly_connection=lambda: sqlite3.connect(
                (runtime / config.work_db).as_uri() + "?mode=ro", uri=True))
        app = OperatorApplication(config, OperatorActions(self.guard))
        auth = McpHostAuthorizer(owner_authorize=lambda p, tool, run:
                                 p.principal_id == "owner@m1" and (not run or run in {g.consent_id for g in self.grants.values()}))
        self.host = AuthenticatedMcpHost(app, auth, human_model_port=self.port)
        self.principal, self.token = self.host.issue_principal("owner@m1", {
            "foundation_status", "human_model_collect", "human_model_correct", "human_model_refresh"})
        auth.register(self.principal, self.token)
        self.approve(self.grants["old"])
        self.call("human_model_collect", self.args("old"))

    def add_source(self, record, text):
        self.grants[record] = HostCollectionGrant(
            owner_id="owner@m1", source_system="chat", source_record_id=record,
            source_revision="revision-1", source_uri="synthetic:chat:"+record,
            scope="work", privacy="private", purpose="independent owner utterance",
            consent_id="collect-"+record, consent_revision="1", expected_sha256=digest(text))
        self.snapshots[record] = TrustedSourceSnapshot(
            source_system="chat", source_record_id=record, source_revision="revision-1",
            source_uri="synthetic:chat:"+record, actor_principal_id="owner@m1",
            actor_kind="owner", actor_verified=True, complete=True, content=text,
            observed_at="2026-11-18T00:00:00+09:00")

    def grant_for(self, owner, system, record, scope, run):
        grant = self.grants[record]
        if (owner, system, scope, run) != (grant.owner_id, grant.source_system, grant.scope, grant.consent_id):
            raise PermissionError("synthetic grant mismatch")
        return grant

    def correction_authority(self, owner, evidence_id, grant,
                             task_id, generation_sha256, answer_evidence_sha256):
        with sqlite3.connect(self.path) as db:
            old = db.execute("SELECT id FROM evidence WHERE source_uri='synthetic:chat:old'").fetchone()
        return (self.permit_correction and owner == "owner@m1"
                and old is not None and evidence_id == old[0]
                and grant == self.grants["new"]
                and task_id == self.task_id
                and generation_sha256 == self.generation
                and answer_evidence_sha256 == self.answer_evidence)

    def approve(self, grant):
        intent = collection_intent(grant, binding=self.binding, canon=self.canon)
        self.store.request_approval(intent.run_id, intent.action, intent.target,
                                    intent.canon_revision, intent.effect_id)
        with sqlite3.connect(self.store.path) as db:
            row = db.execute("SELECT action,target,request_nonce,canon_revision,effect_id "
                             "FROM approval_requests WHERE run_id=?", (intent.run_id,)).fetchone()
        self.assertTrue(OperatorActions(self.guard).approve_pending(
            intent.run_id, approval_request_ref(intent.run_id, *row)).ok)

    def args(self, record):
        return {"source_system": "chat", "record_id": record, "scope": "work",
                "run_id": self.grants[record].consent_id}

    def correction_args(self):
        return {**self.args("new"),
                "corrects_evidence_sha256": self.grants["old"].expected_sha256,
                "task_id": self.task_id,
                "generation_sha256": self.generation,
                "answer_evidence_sha256": self.answer_evidence}

    def call(self, tool, args):
        return self.host.dispatch(self.principal.session_id, self.token, tool, args)

    def count(self):
        with sqlite3.connect(self.path) as db:
            return db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]

    def test_exact_native_owner_correction_preserves_original_and_replays_once(self):
        self.approve(self.grants["new"])
        result = self.call("human_model_correct", self.correction_args())
        self.assertEqual(result["status"], "SOURCE_PUBLISHED")
        self.assertTrue(result["source_correction_recorded"])
        self.assertTrue(result["original_answer_verified"])
        self.assertFalse(result["execution_authority"])
        self.assertFalse(result["views_rebuilt"])
        self.assertNotIn("PRIVATE_SOURCE", repr(result))
        with sqlite3.connect(self.path) as db:
            old = db.execute("SELECT id,content FROM evidence WHERE source_uri='synthetic:chat:old'").fetchone()
            new = db.execute("SELECT supersedes,kind FROM evidence WHERE source_uri='synthetic:chat:new'").fetchone()
            self.assertEqual(old[1], "ORIGINAL_PRIVATE_SOURCE")
            self.assertEqual(new, (old[0], "observation"))
            self.assertEqual(db.execute("SELECT stale FROM model_views").fetchone()[0], 1)
        replay = self.call("human_model_correct", self.correction_args())
        self.assertEqual(replay["status"], "SOURCE_ALREADY_CURRENT")
        self.assertEqual(self.count(), 2)
        report = self.call("human_model_refresh", {})
        self.assertEqual(report['status'], 'OWNER_LIFECYCLE_VERIFIED')
        with closing(Ledger(self.path)) as ledger:
            # A maintenance receipt is not a rebuilt-view receipt. Never
            # serve a stale answer merely because a correction was saved.
            with self.assertRaisesRegex(RuntimeError, 'stale'):
                ledger.query(view_id="owner-view", scope="work", audience="foundation")

    def test_missing_or_mismatched_original_answer_reference_fails_closed(self):
        self.approve(self.grants["new"])
        cases = [
            {"task_id": "other-task"},
            {"generation_sha256": digest("wrong-generation")},
            {"answer_evidence_sha256": digest("wrong-answer")},
            {"answer_evidence_sha256": "wrong"},
        ]
        for change in cases:
            args = {**self.correction_args(), **change}
            with self.subTest(change=change):
                with self.assertRaises((PermissionError, ValueError)):
                    self.call("human_model_correct", args)
                self.assertEqual(self.count(), 1)
        with self.assertRaises(ValueError):
            self.call("human_model_correct", {
                key: val for key, val in self.correction_args().items()
                if key != "task_id"})

    def test_later_review_generation_invalidates_old_answer_correction(self):
        self.approve(self.grants["new"])
        self.reviews.started(self.task_id, digest("new-question-generation"))
        with self.assertRaisesRegex(PermissionError, "CURRENT_OWNER_ANSWER"):
            self.call("human_model_correct", self.correction_args())
        self.assertEqual(self.count(), 1)

    def test_original_answer_must_have_real_resolved_work_receipt(self):
        self.approve(self.grants["new"])
        with sqlite3.connect(self.reviews.path) as db:
            db.execute(
                "UPDATE primary_review_transitions SET outcome='NO_MATCHING_EVIDENCE' "
                "WHERE job_id=? AND event='PRIMARY_REVIEW_RESOLVED'",
                (self.task_id,))
        with self.assertRaisesRegex(PermissionError, "CURRENT_OWNER_ANSWER"):
            self.call("human_model_correct", self.correction_args())
        self.assertEqual(self.count(), 1)

    def test_collection_permission_alone_cannot_correct(self):
        with self.assertRaises(PermissionError):
            self.call("human_model_correct", self.correction_args())
        self.approve(self.grants["new"])
        self.permit_correction = False
        with self.assertRaisesRegex(PermissionError, "CORRECTION_DENIED"):
            self.call("human_model_correct", self.correction_args())
        self.assertEqual(self.count(), 1)

    def test_self_declared_muse_owner_is_not_native_owner_proof(self):
        self.approve(self.grants["new"])
        self.snapshots["new"] = replace(self.snapshots["new"], actor_kind="assistant")
        with self.assertRaisesRegex(PermissionError, "UNVERIFIED_OWNER_SOURCE"):
            self.call("human_model_correct", self.correction_args())
        self.assertEqual(self.count(), 1)

    def test_duplicate_digest_or_wrong_scope_never_selects_favourable_source(self):
        self.approve(self.grants["new"])
        with self.assertRaises(ValueError):
            self.call("human_model_correct", {**self.correction_args(), "scope": "other"})
        self.add_source("duplicate", "ORIGINAL_PRIVATE_SOURCE")
        self.approve(self.grants["duplicate"])
        self.call("human_model_collect", self.args("duplicate"))
        with self.assertRaisesRegex(PermissionError, "NOT_UNIQUE"):
            self.call("human_model_correct", self.correction_args())
        self.assertEqual(self.count(), 2)

    def test_correction_capability_is_opt_in_and_raw_text_is_rejected(self):
        self.assertIn("human_model_correct", self.host.tool_catalog())
        self.port.open_review_readonly_connection = None
        self.assertNotIn("human_model_correct", self.host.tool_catalog())
        self.port.open_review_readonly_connection = lambda: sqlite3.connect(
            self.reviews.path.as_uri() + "?mode=ro", uri=True)
        self.port.authorize_correction = None
        self.assertNotIn("human_model_correct", self.host.tool_catalog())
        with self.assertRaises(PermissionError):
            self.call("human_model_correct", self.correction_args())
        with self.assertRaises(ValueError):
            self.call("human_model_correct", {**self.correction_args(), "text": "pretend owner"})
        schema = next(x["inputSchema"] for x in BOUND_TOOLS if x["name"] == "human_model_correct")
        self.assertFalse(schema["additionalProperties"])
        self.assertNotIn("text", schema["properties"])
        service = MCPStdio(self.host, self.principal.session_id, self.token)
        self.assertNotIn("human_model_correct", service.exposed_tools)

    def test_session_scope_and_source_revision_remain_independent_requirements(self):
        self.approve(self.grants["new"])
        other, token = self.host.issue_principal("owner@m1", {"human_model_collect"})
        self.host.authorizer.register(other, token)
        with self.assertRaises(PermissionError):
            self.host.dispatch(other.session_id, token, "human_model_correct", self.correction_args())
        self.snapshots["new"] = replace(self.snapshots["new"], content="CHANGED_PRIVATE_TEXT")
        with self.assertRaisesRegex(PermissionError, "CONTENT_CHANGED"):
            self.call("human_model_correct", self.correction_args())
        self.assertEqual(self.count(), 1)

    def test_correction_authority_binds_exact_old_source_not_just_owner(self):
        self.add_source("other", "UNRELATED_PRIVATE_SOURCE")
        self.approve(self.grants["other"])
        self.call("human_model_collect", self.args("other"))
        self.approve(self.grants["new"])
        with self.assertRaisesRegex(PermissionError, "CORRECTION_DENIED"):
            self.call("human_model_correct", {**self.correction_args(),
                     "corrects_evidence_sha256": self.grants['other'].expected_sha256})
        self.assertEqual(self.count(), 2)

    def test_real_mcp_framing_exposes_only_host_selected_correction_tools(self):
        self.approve(self.grants['new'])
        service = MCPStdio(self.host, self.principal.session_id, self.token,
                           exposed_tools=('foundation_status', 'human_model_correct', 'human_model_refresh'))
        service.dispatch({'jsonrpc':'2.0', 'id':1, 'method':'initialize', 'params':{}})
        service.dispatch({'jsonrpc':'2.0', 'method':'notifications/initialized'})
        listing = service.dispatch({'jsonrpc':'2.0', 'id':2, 'method':'tools/list'})
        self.assertEqual({t['name'] for t in listing['result']['tools']},
                         {'foundation_status', 'human_model_correct', 'human_model_refresh'})
        response = service.dispatch({'jsonrpc':'2.0', 'id':3, 'method':'tools/call',
                                     'params': {'name':'human_model_correct', 'arguments':self.correction_args()}})
        self.assertFalse(response['result']['isError'])
        self.assertEqual(json.loads(response['result']['content'][0]['text'])['status'], 'SOURCE_PUBLISHED')
        self.assertNotIn('PRIVATE_SOURCE', repr(response))
        denied = service.dispatch({'jsonrpc':'2.0', 'id':4, 'method':'tools/call',
                                   'params': {'name':'human_model_correct',
                                              'arguments':{**self.correction_args(), 'owner':'self-claimed'}}})
        self.assertEqual(denied['error']['code'], -32602)
        self.assertEqual(self.count(), 2)


if __name__ == "__main__":
    unittest.main()
