"""Existing release-ledger selection; fixtures never touch host services."""
import json
import hashlib
from pathlib import Path
import plistlib
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ai_foundation.release_gate import GuardReleaseGate, ImmutableReleaseScope
from ai_foundation.store import SQLiteGuardStore
from scripts.m1_operator_release_host import FixedOperatorHost, OperatorHostDenied
from scripts import m1_operator_release_host as host_module


def scope(commit, previous="owner-installed:old"):
    return ImmutableReleaseScope(
        path="m1-operator", source_sha="a"*64,
        previous_authority=previous, previous_endpoint="launchd:operator",
        candidate_authority="github-commit:" + (commit if len(commit) == 40 else commit*40),
        candidate_endpoint="launchd:operator", rollback_procedure="restore",
        switch_target="operator-only", readback_target="pid-api",
        rollback_readback_target="prior-pid-api")


class LedgerSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.primary = self.root / "operator-only-release-registry.json"
        self.old = scope("b")
        self.current = scope("c")
        self.successor = scope("d", "owner-installed:current")
        self.host = object.__new__(FixedOperatorHost)
        self.host.home = self.root
        self.host.source_root = self.root
        self.host.git_run = None
        self.host.plist = self.root / "operator.plist"
        self.host.plist.write_bytes(plistlib.dumps({
            "Label": host_module.LABEL, "ProgramArguments": ["/usr/bin/python3",
            str(self.root / "Library/Application Support/AI-Foundation/operator-release-staging"
                / self.current.scope_ref / "candidate/scripts/operator_server.py")]}))
        self.host.plist.chmod(0o600)
        self.probes = []
        self.host.verified_current_release = lambda record: (
            self.probes.append(record.release_scope_ref)
            or record.release_scope_ref == self.current.scope_ref)
        self.save(self.primary, self.old)
        self.owner = self.owner_path(self.current)
        self.save(self.owner, self.current)

    def owner_path(self, item):
        return self.root / ("operator-owner-main-release-" + item.scope_ref[:20] + ".json")

    def save(self, path, item, status="VERIFIED"):
        row = {key: value for key, value in item.as_dict().items() if key != "source_sha"}
        row.update(status=status, updated_at=1, generation=1,
                   release_scope=item.as_dict(), release_scope_ref=item.scope_ref,
                   release_run_id="release-1", release_request_ref="f"*64,
                   release_canon_revision="canon-source/v1:"+"e"*64)
        path.write_text(json.dumps({"schema": 2, "paths": {
            "m1-operator": {**row, "history": [row]}}}))
        path.chmod(0o600)

    def test_unique_proven_owner_ledger_selected_without_rewriting_legacy(self):
        before = {path: path.read_bytes() for path in (self.primary, self.owner)}
        self.assertEqual(self.host.select_release_registry(self.primary), self.owner)
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertEqual(self.probes, [self.current.scope_ref])

    def test_existing_gate_prepares_and_resumes_same_ledger_without_approval(self):
        legacy = self.primary.read_bytes()
        store = SQLiteGuardStore(self.root / "guard.sqlite")
        selected = self.host.select_release_registry(self.primary)
        gate = GuardReleaseGate(store, selected)
        result = gate.prepare(self.successor, canon_revision="canon-source/v1:"+"e"*64,
                              verified_predecessor_ref=self.current.scope_ref)
        self.assertEqual(result["status"], "WAITING_HUMAN")
        self.assertFalse(result["release_permitted"])
        self.assertEqual(self.host.select_release_registry(
            self.primary, scope=self.successor), self.owner)
        self.assertEqual(gate.verify(self.successor, result["run_id"], result["request_ref"])["status"],
                         "OWNER_APPROVAL_REQUIRED")
        self.assertEqual(self.primary.read_bytes(), legacy)
        self.assertEqual([row.status for row in gate.registry.history("m1-operator")],
                         ["VERIFIED", "PREPARED"])
        with self.assertRaisesRegex(OperatorHostDenied, "INFLIGHT_SCOPE_MISMATCH"):
            self.host.select_release_registry(self.primary, scope=self.old)

    def test_unproven_ledger_does_not_replace_legacy(self):
        self.host.verified_current_release = lambda record: False
        with self.assertRaisesRegex(OperatorHostDenied, "VERIFIED_INCUMBENT_UNIDENTIFIED"):
            self.host.select_release_registry(self.primary)

    def test_unmatched_verified_sibling_blocks_absent_or_rolled_back_primary(self):
        self.host.verified_current_release = lambda record: False
        self.primary.unlink()
        with self.assertRaisesRegex(OperatorHostDenied, "VERIFIED_INCUMBENT_UNIDENTIFIED"):
            self.host.select_release_registry(self.primary)
        self.save(self.primary, self.old, status="ROLLED_BACK")
        with self.assertRaisesRegex(OperatorHostDenied, "VERIFIED_INCUMBENT_UNIDENTIFIED"):
            self.host.select_release_registry(self.primary)

    def test_fallback_is_only_for_no_verified_or_inflight_records(self):
        self.save(self.owner, self.current, status="ROLLED_BACK")
        self.save(self.primary, self.old, status="ROLLED_BACK")
        self.assertEqual(self.host.select_release_registry(self.primary), self.primary)
        self.primary.unlink()
        self.assertEqual(self.host.select_release_registry(self.primary), self.primary)

    def test_actual_staged_source_and_loaded_definition_proof_is_required(self):
        del self.host.verified_current_release
        stage = (self.root / "Library/Application Support/AI-Foundation"
                 / "operator-release-staging" / self.current.scope_ref)
        candidate = stage / "candidate"
        entry = candidate / "scripts/operator_server.py"
        entry.parent.mkdir(parents=True, mode=0o700)
        stage.chmod(0o700)
        old_entry = self.root / "original_operator.py"
        old_source = b"# original source\n"
        original = plistlib.dumps({"Label": host_module.LABEL,
            "ProgramArguments": ["/usr/bin/python3", "-B", str(old_entry),
                                 "--config", str(self.root / "config.json")]})
        source = b"# accepted source\n"
        digest = lambda raw: hashlib.sha256(raw).hexdigest()
        manifest = {"schema": 1, "scope_ref": self.current.scope_ref,
                    "candidate_commit": "c"*40,
                    "prior_plist_sha256": digest(original),
                    "prior_entry_sha256": digest(old_source),
                    "prior_entry_path": str(old_entry),
                    "tracked": {"scripts/operator_server.py": digest(source)}}
        for path, raw in ((entry, source), (old_entry, old_source),
                          (stage / "previous-launchagent.plist", original),
                          (stage / "previous-operator-entry.py", old_source),
                          (stage / "manifest.json", json.dumps(manifest).encode())):
            path.write_bytes(raw)
            path.chmod(0o600)
        definition, _ = host_module.candidate_operator_plist(original, old_entry, candidate)
        self.host.plist = self.root / "operator.plist"
        self.host.plist.write_bytes(definition)
        self.host.plist.chmod(0o600)
        self.host.target = "gui/501/" + host_module.LABEL
        row = plistlib.loads(definition)
        loaded = ("program = " + row["ProgramArguments"][0] + "\narguments = {\n"
                  + "\n".join(row["ProgramArguments"]) + "\n}\nworking directory = "
                  + row["WorkingDirectory"] + "\nenvironment = {\n"
                  + "\n".join(key + " => " + value for key, value in
                              row["EnvironmentVariables"].items()) + "\n}\n")
        self.host._launch = lambda *a: SimpleNamespace(returncode=0, stdout=loaded)
        self.host._pid_owned = lambda: True
        self.host._human = lambda: {"activity": []}
        with patch.object(host_module, "_verified_owner_code_workspace", return_value=None):
            self.assertEqual(self.host.select_release_registry(self.primary), self.owner)
            loaded = loaded.replace(row["EnvironmentVariables"]["PYTHONPATH"], "/stale")
            with self.assertRaisesRegex(OperatorHostDenied, "VERIFIED_INCUMBENT_UNIDENTIFIED"):
                self.host.select_release_registry(self.primary)
            entry.write_bytes(b"# changed source\n")
            with self.assertRaisesRegex(OperatorHostDenied, "VERIFIED_INCUMBENT_UNIDENTIFIED"):
                self.host.select_release_registry(self.primary)

    def test_older_prepared_with_newer_live_verified_selects_without_rewrite(self):
        old_pending = self.owner_path(scope("e"))
        self.save(self.primary, self.old, status="PREPARED")
        self.save(old_pending, scope("e"), status="PREPARED")
        # Establish strictly later owner-written VERIFIED receipt.
        doc = json.loads(self.owner.read_text())
        doc["paths"]["m1-operator"]["updated_at"] = 20
        doc["paths"]["m1-operator"]["history"][-1]["updated_at"] = 20
        self.owner.write_text(json.dumps(doc))
        before = {p: p.read_bytes()
                  for p in (self.primary, self.owner, old_pending)}
        self.assertEqual(self.host.select_release_registry(
            self.primary, scope=self.successor), self.owner)
        self.assertEqual(self.host.superseded_prepared_count, 2)
        self.assertEqual({p: p.read_bytes() for p in before}, before)

        # Neither a scope matching an in-flight release nor a missing live
        # source may bypass the historical journal's pending state.
        with self.assertRaisesRegex(OperatorHostDenied, "RELEASE_MULTIPLE_INFLIGHT"):
            self.host.select_release_registry(self.primary, scope=self.old)
        self.host.verified_current_release = lambda record: False
        with self.assertRaisesRegex(OperatorHostDenied, "RELEASE_MULTIPLE_INFLIGHT"):
            self.host.select_release_registry(self.primary, scope=self.successor)
        self.assertEqual(self.host.superseded_prepared_count, 0)
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_owner_request_to_apply_reselects_prepared_successor(self):
        # Match the real production scenario: multiple older owner-main
        # PREPARED journals plus a newer live and VERIFIED predecessor.
        # The new Guard request moves that *same* valid owner ledger to
        # PREPARED while the previous executable remains loaded.
        extra = self.owner_path(scope("e"))
        self.save(self.primary, self.old, status="PREPARED")
        self.save(extra, scope("e"), status="PREPARED")
        source = json.loads(self.owner.read_text())
        source["paths"]["m1-operator"]["updated_at"] = 20
        source["paths"]["m1-operator"]["history"][-1]["updated_at"] = 20
        self.owner.write_text(json.dumps(source))
        store = SQLiteGuardStore(self.root / "guard.sqlite")
        selected = self.host.select_release_registry(self.primary,
                                                     scope=self.successor)
        self.assertEqual(selected, self.owner)
        gate = GuardReleaseGate(store, selected)
        pending = gate.prepare(self.successor,
                               canon_revision="canon-source/v1:"+"e"*64,
                               verified_predecessor_ref=self.current.scope_ref)
        self.assertEqual(pending["status"], "WAITING_HUMAN")
        self.assertEqual(self.host.select_release_registry(
            self.primary, scope=self.successor), self.owner)
        # CLI _guard_gate has no input scope, so it must also find the exact
        # prepared successor for apply (not one of the four stale ledgers).
        self.assertEqual(self.host.select_release_registry(self.primary),
                         self.owner)
        self.assertEqual(self.host.superseded_prepared_count, 2)
        gate_after = GuardReleaseGate(store,
                                     self.host.select_release_registry(self.primary))
        self.assertEqual(
            gate_after.verify(self.successor, pending["run_id"],
                              pending["request_ref"])["status"],
            "OWNER_APPROVAL_REQUIRED")
        self.assertEqual(
            json.loads(self.primary.read_text())["paths"]["m1-operator"]["status"],
            "PREPARED")
        self.assertEqual(
            json.loads(extra.read_text())["paths"]["m1-operator"]["status"],
            "PREPARED")
        self.assertEqual(
            [row.status for row in gate_after.registry.history("m1-operator")],
            ["VERIFIED", "PREPARED"])

        # A different requested scope cannot grab the prepared journal.
        with self.assertRaisesRegex(OperatorHostDenied, "RELEASE_MULTIPLE_INFLIGHT"):
            self.host.select_release_registry(self.primary, scope=self.old)
        self.host.verified_current_release = lambda prior: False
        with self.assertRaisesRegex(OperatorHostDenied, "RELEASE_MULTIPLE_INFLIGHT"):
            self.host.select_release_registry(self.primary)

    def test_prepared_successor_cutover_or_tamper_is_never_auto_resumed(self):
        extra = self.owner_path(scope("e"))
        self.save(self.primary, self.old, status="PREPARED")
        self.save(extra, scope("e"), status="PREPARED")
        store = SQLiteGuardStore(self.root / "guard.sqlite")
        gate = GuardReleaseGate(store, self.owner)
        gate.prepare(self.successor, canon_revision="canon-source/v1:"+"e"*64,
                     verified_predecessor_ref=self.current.scope_ref)
        self.save(extra, scope("e"), status="CUTOVER")
        with self.assertRaisesRegex(OperatorHostDenied, "RELEASE_MULTIPLE_INFLIGHT"):
            self.host.select_release_registry(self.primary)
        self.save(extra, scope("e"), status="PREPARED")
        altered = json.loads(self.owner.read_text())
        altered["paths"]["m1-operator"]["history"][-2]["status"] = "ROLLED_BACK"
        self.owner.write_text(json.dumps(altered))
        with self.assertRaisesRegex(OperatorHostDenied, "RELEASE_MULTIPLE_INFLIGHT"):
            self.host.select_release_registry(self.primary)
        # A historical VERIFIED-looking row without a valid immutable
        # source reference cannot authorize selection or crash the host.
        altered["paths"]["m1-operator"]["history"][-2]["status"] = "VERIFIED"
        altered["paths"]["m1-operator"]["history"][-2]["release_scope_ref"] = "bad"
        self.owner.write_text(json.dumps(altered))
        with self.assertRaisesRegex(OperatorHostDenied, "RELEASE_MULTIPLE_INFLIGHT"):
            self.host.select_release_registry(self.primary)

    def test_newer_or_cutover_pending_cannot_be_superseded(self):
        old_pending = self.owner_path(scope("e"))
        self.save(self.primary, self.old, status="PREPARED")
        self.save(old_pending, scope("e"), status="PREPARED")
        # Equal timestamps do not prove chronology: fail closed.
        with self.assertRaisesRegex(OperatorHostDenied, "RELEASE_MULTIPLE_INFLIGHT"):
            self.host.select_release_registry(self.primary, scope=self.successor)
        self.save(old_pending, scope("e"), status="CUTOVER")
        with self.assertRaisesRegex(OperatorHostDenied, "RELEASE_MULTIPLE_INFLIGHT"):
            self.host.select_release_registry(self.primary, scope=self.successor)

    def test_multiple_inflight_audit_is_bounded_no_effect(self):
        self.save(self.primary, self.old, status="ROLLED_BACK")
        self.save(self.owner, self.current, status="PREPARED")
        second = self.owner_path(self.successor)
        self.save(second, self.successor, status="CUTOVER")
        before = {path: path.read_bytes()
                  for path in (self.primary, self.owner, second)}
        with self.assertRaisesRegex(
                OperatorHostDenied, "^RELEASE_MULTIPLE_INFLIGHT$") as caught:
            self.host.select_release_registry(self.primary,
                                              scope=self.successor)
        report = caught.exception.safe_contention
        self.assertEqual((report["total"], report["prepared"],
                          report["cutover"], report["truncated"]),
                         (2, 1, 1, False))
        self.assertEqual({row["state"] for row in report["records"]},
                         {"PREPARED", "CUTOVER"})
        self.assertEqual({row["scope_ref"] for row in report["records"]},
                         {self.current.scope_ref, self.successor.scope_ref})
        self.assertEqual({row["candidate_commit"] for row in report["records"]},
                         {"c"*40, "d"*40})
        self.assertEqual(sum(row["matches_current_candidate"]
                             for row in report["records"]), 1)
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertFalse(self.probes)
        self.assertEqual(report["service_mutations"], 0)

    def test_duplicate_live_ledgers_are_ambiguous(self):
        self.save(self.owner_path(self.successor), self.current)
        with self.assertRaisesRegex(OperatorHostDenied, "^RELEASE_MULTIPLE_VERIFIED_LOADED$"):
            self.host.select_release_registry(self.primary)

    def test_symlink_or_scope_or_history_corruption_is_rejected(self):
        original = self.owner.read_bytes()
        for mutate in (
                lambda row: row.update(candidate_authority="github-commit:"+"f"*40),
                lambda row: row["history"][-1].update(status="CUTOVER")):
            doc = json.loads(original)
            mutate(doc["paths"]["m1-operator"])
            self.owner.write_text(json.dumps(doc))
            with self.assertRaisesRegex(OperatorHostDenied, "UNTRUSTED"):
                self.host.select_release_registry(self.primary)
        self.owner.unlink()
        self.owner.symlink_to(self.primary)
        with self.assertRaisesRegex(OperatorHostDenied, "UNTRUSTED"):
            self.host.select_release_registry(self.primary)

    def test_inflight_ledger_is_never_ignored_for_new_request(self):
        self.save(self.owner, self.successor, status="CUTOVER")
        with self.assertRaisesRegex(OperatorHostDenied, "INFLIGHT_SCOPE_MISMATCH"):
            self.host.select_release_registry(self.primary, scope=self.current)
        self.assertFalse(self.probes)

    def test_enumeration_is_bounded_and_invalid_names_rejected(self):
        invalid = self.root / "operator-owner-main-release-invalid.json"
        invalid.write_text("{}")
        with self.assertRaisesRegex(OperatorHostDenied, "UNTRUSTED"):
            self.host.select_release_registry(self.primary)
        invalid.unlink()
        for index in range(513):
            (self.root / f"operator-owner-main-release-{index:020x}.json").write_text("{}")
        with self.assertRaisesRegex(OperatorHostDenied, "UNBOUNDED"):
            self.host.select_release_registry(self.primary)

    def test_many_small_historical_ledgers_only_probe_matching_candidate(self):
        for index in range(100):
            item = scope(f"{index:040x}")
            self.save(self.owner_path(item), item)
        self.assertEqual(self.host.select_release_registry(self.primary), self.owner)
        self.assertEqual(self.probes, [self.current.scope_ref])

    def test_total_read_budget_and_oversized_file_fail_before_proof(self):
        self.owner.write_bytes(self.owner.read_bytes() + b" "*500000)
        with self.assertRaisesRegex(OperatorHostDenied, "UNTRUSTED"):
            self.host.select_release_registry(self.primary)
        self.save(self.owner, self.current)
        for index in range(34):
            item = scope(f"{index:040x}")
            path = self.owner_path(item)
            self.save(path, item)
            raw = path.read_bytes()
            path.write_bytes(raw + b" "*(480000-len(raw)))
        with self.assertRaisesRegex(OperatorHostDenied, "INVENTORY_UNBOUNDED"):
            self.host.select_release_registry(self.primary)
        self.assertFalse(self.probes)


if __name__ == "__main__":
    unittest.main()
