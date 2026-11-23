"""Fixed M1 Operator-only launchd adapter, never an MCP or HTTP tool.

Requires the separately approved two-gate OperatorOnlyCutover. No main
entrypoint is provided: PR/M1 read-only acceptance cannot activate it.
"""
from __future__ import annotations

import hashlib
import http.client
from itertools import islice
import json
import math
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import tempfile
import time

from scripts.m1_operator_release_stage import (
    StagingDenied, stage_operator_only, verify_staged, _read_private)
from scripts.m1_p4_release_inventory import (
    _owned_regular_bytes, _source_from_plist, operator_only_release_scope,
    require_m1, LABELS)


class OperatorHostDenied(RuntimeError):
    def __init__(self, reason, *, safe_contention=None):
        super().__init__(reason)
        # Only the owner's bounded, validated ledger-state summary. No paths,
        # authorization request refs, source text or mutable state leave M1.
        self.safe_contention = safe_contention


LABEL = LABELS[0][1]
PORT = 8766
HTTP_LIMIT = 262144


# Exact source revision from the independently Guard-VERIFIED owner CODE
# recovery #1141; never infer a different workspace or mount from config.
REVIEWED_CODE_HEAD = "48f57783c303f2f18fad9d5e425dada79d32f1e3"


def _verified_owner_code_workspace(home):
    """Read-only original recovery checks; no CODE lifecycle or host write.

    If the separate workspace exists but differs, fail the entire release
    rather than silently binding an unreviewed mount or skipping CODE.
    """
    from types import SimpleNamespace
    from scripts.m1_owner_toolhive_code_repair import (
        NAME, FixedCodeWorkload, git,
    )
    from scripts.m1_owner_toolhive_files_repair import (
        DOCKER_BINARIES, EXPECTED_IMAGE_ID, pinned_container_image,
    )
    from ai_foundation.toolhive_owner_runtime import owner_toolhive_binary

    workspace = Path(home) / "Develop/AI-Foundation-CODE"
    if not workspace.exists() and not workspace.is_symlink():
        return None
    try:
        info = workspace.lstat()
        metadata = workspace / ".git"
        if (not stat.S_ISDIR(info.st_mode) or workspace.is_symlink()
                or info.st_uid != os.getuid() or info.st_mode & 0o022
                or metadata.is_symlink() or not metadata.is_dir()
                or git(workspace, "rev-parse", "--git-common-dir") != ".git"
                or git(workspace, "rev-parse", "--show-toplevel")
                    != str(workspace.resolve())
                or git(workspace, "rev-parse", "HEAD") != REVIEWED_CODE_HEAD
                or git(workspace, "remote")
                or git(workspace, "status", "--porcelain")
                or git(workspace, "ls-files", "--others", "--ignored",
                       "--exclude-standard", "--directory")
                or (metadata / "objects/info/alternates").exists()):
            raise OperatorHostDenied("CODE_WORKSPACE_IDENTITY_UNVERIFIED")
        binary = owner_toolhive_binary(Path(home))
        docker = next((p for p in DOCKER_BINARIES if Path(p).is_file()), None)
        if binary is None or docker is None:
            raise OperatorHostDenied("CODE_WORKLOAD_PROVENANCE_UNVERIFIED")
        pinned_container_image(EXPECTED_IMAGE_ID)
        probe = FixedCodeWorkload(binary, workspace, docker)
        # observe() only reads ToolHive/Docker/MCP; this flag selects the
        # fully pinned post-create readback, not a new dispatch.
        probe.dispatches = 1
        if probe.observe(SimpleNamespace(target="toolhive:" + NAME)) != "RUNNING_VERIFIED_MOUNT":
            raise OperatorHostDenied("CODE_WORKLOAD_PROVENANCE_UNVERIFIED")
        return workspace
    except OperatorHostDenied:
        raise
    except (OSError, RuntimeError, ValueError, TypeError, KeyError,
            subprocess.TimeoutExpired):
        raise OperatorHostDenied("CODE_WORKLOAD_PROVENANCE_UNVERIFIED") from None



def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _loaded_arguments_match(output, expected):
    """Read only launchd's single arguments block, never incidental paths."""
    if type(output) is not str or type(expected) is not list or not expected:
        return False
    blocks = re.findall(r"^\s*arguments = \{\s*\n(.*?)^\s*\}\s*$",
                        output, re.M | re.S)
    if len(blocks) != 1:
        return False
    arguments = [line.strip() for line in blocks[0].splitlines()]
    programs = re.findall(r"^\s*program = (.+?)\s*$", output, re.M)
    return arguments == expected and programs == [expected[0]]


def _loaded_definition_match(output, definition):
    if not _loaded_arguments_match(output, definition.get("ProgramArguments")):
        return False
    directories = re.findall(r"^\s*working directory = (.+?)\s*$", output, re.M)
    if directories != [definition.get("WorkingDirectory")]:
        return False
    blocks = re.findall(r"^\s*environment = \{\s*\n(.*?)^\s*\}\s*$",
                        output, re.M | re.S)
    if len(blocks) != 1:
        return False
    environment = {}
    for line in blocks[0].splitlines():
        pair = line.strip().split(" => ", 1)
        if len(pair) != 2 or pair[0] in environment:
            return False
        environment[pair[0]] = pair[1]
    expected = definition.get("EnvironmentVariables")
    if type(expected) is not dict or any(
            type(key) is not str or type(value) is not str
            or environment.get(key) != value for key, value in expected.items()):
        return False
    # These unreviewed overrides would change Python's imported code even
    # when the entrypoint and expected environment keys match.
    return not any(key in environment and key not in expected
                   for key in ("PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE"))


def candidate_operator_plist(original, old_script, staged_checkout, *, code_workspace=None):
    """Exact fixed Operator replacement; never execute commands from a plist."""
    obj = plistlib.loads(original)
    args = obj.get("ProgramArguments")
    if obj.get("Label") != LABEL or type(args) is not list:
        raise OperatorHostDenied("OPERATOR_LABEL_OR_ARGS_MISMATCH")
    scripts = [x for x in args if type(x) is str and x.startswith("/")
               and x.endswith(".py")]
    if scripts != [str(old_script)] or args.count(str(old_script)) != 1:
        raise OperatorHostDenied("ORIGINAL_OPERATOR_ENTRY_MISMATCH")
    i = args.index(str(old_script))
    interpreter = args[0] if args else ""
    if (type(interpreter) is not str or not interpreter.startswith("/")
            or re.fullmatch(r"python(?:3(?:\.\d+)?)?",
                            Path(interpreter).name) is None
            or any(x not in ("-B", "-u") for x in args[1:i])):
        raise OperatorHostDenied("UNREVIEWED_PYTHON_LAUNCHER")
    trailing = args[i+1:]
    if (len(trailing) % 2 != 0
            or any(type(v) is not str for v in trailing)):
        raise OperatorHostDenied("UNREVIEWED_OPERATOR_OPTIONS")
    pairs = dict(zip(trailing[::2], trailing[1::2]))
    if (len(pairs)*2 != len(trailing) or set(pairs) - {"--config", "--port"}
            or "--config" not in pairs):
        raise OperatorHostDenied("UNREVIEWED_OPERATOR_OPTIONS")
    cfg = Path(pairs["--config"])
    if not cfg.is_absolute() or ".." in cfg.parts:
        raise OperatorHostDenied("OWNER_CONFIG_NOT_ABSOLUTE")
    if pairs.get("--port", "8766") != "8766":
        raise OperatorHostDenied("OPERATOR_PORT_CHANGED")
    staged_checkout = Path(staged_checkout)
    if (not staged_checkout.is_absolute() or ".." in staged_checkout.parts
            or staged_checkout.is_symlink()):
        raise OperatorHostDenied("CANDIDATE_ROOT_UNTRUSTED")
    script = staged_checkout/"scripts/operator_server.py"
    if not script.is_file() or script.is_symlink():
        raise OperatorHostDenied("PINNED_OPERATOR_ENTRY_MISSING")
    updated = dict(obj)
    updated["ProgramArguments"] = (
        [interpreter] + args[1:i] + [str(script), "--config", str(cfg),
                                    "--port", "8766"])
    updated["WorkingDirectory"] = str(staged_checkout)
    env = dict(obj.get("EnvironmentVariables") or {})
    env["PYTHONPATH"] = str(staged_checkout/"src") + ":" + str(
        staged_checkout/"experiments/human_model")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if code_workspace is not None:
        reviewed = Path(code_workspace)
        if (not reviewed.is_absolute() or ".." in reviewed.parts
                or reviewed == staged_checkout
                or env.get("AI_FOUNDATION_REPO_ROOT") not in (None, str(reviewed))
                or env.get("AI_FOUNDATION_TOOLHIVE_REPO_SERVER") not in
                   (None, "ai-foundation-repo")):
            raise OperatorHostDenied("CODE_OPERATOR_BINDING_CHANGED")
        env["AI_FOUNDATION_REPO_ROOT"] = str(reviewed)
        env["AI_FOUNDATION_TOOLHIVE_REPO_SERVER"] = "ai-foundation-repo"
    updated["EnvironmentVariables"] = env
    return plistlib.dumps(updated), str(script)


class FixedOperatorHost:
    """Concrete owner-local backend. No public CLI, no approval issuer.

    This backend alone grants no authority. OwnerOnlyCutover requires an
    independently trusted host owner gate and exact approved Guard ref before
    calling any staging or service methods.
    """

    def __init__(self, source_root, *, home=None, git_run=subprocess.run):
        require_m1()
        if os.getuid() != 501 or os.geteuid() != os.getuid():
            raise OperatorHostDenied("M1_OWNER_SESSION_REQUIRED")
        self.home = Path.home() if home is None else Path(home)
        self.source_root = Path(source_root)
        self.git_run = git_run
        self.plist = self.home/"Library/LaunchAgents"/(LABEL+".plist")
        self.target = f"gui/{os.getuid()}/{LABEL}"
        self.stage = None
        self.expected_scope = None
        self.candidate_definition = None
        self.candidate_script = None

    def current_scope_ref(self):
        scope, receipt = operator_only_release_scope(
            home=self.home, root=self.source_root, git_run=self.git_run)
        return scope.scope_ref if scope and receipt.get("status") == "OBSERVED" else None

    def select_release_registry(self, primary, *, scope=None):
        """Select an existing owner ledger, never reconcile or grant authority.

        The owner-main release entrypoint historically used a separate ledger
        per release. A newer legitimate installation therefore need not be the
        incumbent in the older Operator-only ledger. Only exact loaded source,
        launch definition, PID and API proof can select a VERIFIED record.
        All future intent and history stay in that same existing ledger.
        """
        from types import SimpleNamespace
        from ai_foundation.release_gate import ImmutableReleaseScope

        primary = Path(primary)
        self.superseded_prepared_count = 0
        siblings = list(islice(primary.parent.glob(
            "operator-owner-main-release-*.json"), 513))
        if not siblings:
            return primary
        if len(siblings) > 512:
            raise OperatorHostDenied("RELEASE_LEDGER_INVENTORY_UNBOUNDED")
        if any(re.fullmatch(r"operator-owner-main-release-[0-9a-f]{20}\.json",
                            path.name) is None for path in siblings):
            raise OperatorHostDenied("RELEASE_LEDGER_UNTRUSTED")
        paths = ([primary] if primary.exists() or primary.is_symlink() else []) + sorted(siblings)
        if len(paths) > 512:
            raise OperatorHostDenied("RELEASE_LEDGER_INVENTORY_UNBOUNDED")
        records = []
        total_bytes = 0
        for path in paths:
            try:
                # Many small historical receipts are legitimate. Bound the
                # actual read volume rather than repeatedly hashing every
                # historical staged source package or probing its workloads.
                size = path.lstat().st_size
                if size > 500000:
                    raise ValueError("oversized ledger")
                if total_bytes + size > 16000000:
                    raise OperatorHostDenied("RELEASE_LEDGER_INVENTORY_UNBOUNDED")
                raw = _owned_regular_bytes(path, max_bytes=min(500000, 16000000 - total_bytes))
                total_bytes += len(raw)
                if total_bytes > 16000000:
                    raise OperatorHostDenied("RELEASE_LEDGER_INVENTORY_UNBOUNDED")
                doc = json.loads(raw)
                if (type(doc) is not dict or doc.get("schema") not in (1, 2)
                        or type(doc.get("paths")) is not dict):
                    raise ValueError("invalid ledger")
                row = doc["paths"].get("m1-operator")
                if row is None and path == primary:
                    continue
                if (type(row) is not dict or row.get("path") != "m1-operator"
                        or row.get("status") not in {"PREPARED", "CUTOVER", "VERIFIED", "ROLLED_BACK"}
                        or type(row.get("release_scope")) is not dict
                        or type(row.get("candidate_authority")) is not str
                        or re.fullmatch(r"github-commit:[0-9a-f]{40}", row["candidate_authority"]) is None
                        or row["release_scope"].get("candidate_authority") != row["candidate_authority"]
                        or row["release_scope"].get("path") != "m1-operator"):
                    raise ValueError("invalid record")
                recorded_scope = ImmutableReleaseScope(**row["release_scope"])
                if (recorded_scope.scope_ref != row.get("release_scope_ref")
                        or any(row.get(key) != value for key, value in
                               recorded_scope.as_dict().items() if key != "source_sha")
                        or type(row.get("release_run_id")) is not str
                        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", row["release_run_id"]) is None
                        or type(row.get("release_request_ref")) is not str
                        or re.fullmatch(r"[0-9a-f]{64}", row["release_request_ref"]) is None
                        or type(row.get("release_canon_revision")) is not str
                        or not row["release_canon_revision"].startswith("canon-source/v1:")):
                    raise ValueError("invalid scope binding")
                if doc["schema"] == 2:
                    history = row.get("history")
                    fields = ("status", "release_scope_ref", "release_scope", "candidate_authority",
                              "release_run_id", "release_request_ref", "release_canon_revision", "generation")
                    if (type(history) is not list or not history or type(history[-1]) is not dict
                            or any(history[-1].get(key) != row.get(key) for key in fields)):
                        raise ValueError("invalid history")
                records.append((path, SimpleNamespace(**row)))
            except (OSError, ValueError, TypeError, KeyError, plistlib.InvalidFileException):
                raise OperatorHostDenied("RELEASE_LEDGER_UNTRUSTED") from None
        active = [(path, record) for path, record in records
                  if record.status in {"PREPARED", "CUTOVER"}]
        # Historical PREPARED receipts may survive a newer, independently
        # VERIFIED owner release. Do not mutate or reclassify those receipts.
        # Only a single *currently loaded* newer immutable source, matching
        # launchd definition + PID + API, can safely supersede them for new
        # release selection. A CUTOVER, missing/malformed timestamp, a
        # currently requested in-flight scope, or ambiguous live evidence
        # retains the original fail-closed selection behavior.
        if (active and all(record.status == "PREPARED" for _, record in active)
                and (scope is None or all(
                    record.release_scope_ref != scope.scope_ref
                    for _, record in active))):
            verified = [(path, record) for path, record in records
                        if record.status == "VERIFIED"]
            dated = [record for _, record in active]
            if all(type(getattr(record, "updated_at", None)) in (int, float)
                   and math.isfinite(record.updated_at) and record.updated_at > 0
                   for record in dated):
                try:
                    installed = plistlib.loads(
                        _owned_regular_bytes(self.plist, max_bytes=32768))
                    args = installed.get("ProgramArguments")
                    if (installed.get("Label") != LABEL or type(args) is not list
                            or any(type(arg) is not str for arg in args)):
                        raise ValueError("untrusted launch definition")
                    matching = [(path, record) for path, record in verified
                                if args.count(str(
                                    self.home / "Library/Application Support/AI-Foundation"
                                    / "operator-release-staging" / record.release_scope_ref
                                    / "candidate/scripts/operator_server.py")) == 1]
                except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
                    matching = []
                if len(matching) == 1:
                    live_path, live_record = matching[0]
                    when = getattr(live_record, "updated_at", None)
                    if (type(when) in (int, float)
                            and math.isfinite(when)
                            and when > max(row.updated_at for row in dated)
                            and self.verified_current_release(live_record) is True):
                        self.superseded_prepared_count = len(active)
                        return live_path
        # Once the owner has requested a new Guard approval, the
        # independently loaded VERIFIED predecessor is still running, but
        # its *same* release ledger now ends in PREPARED. The first selection
        # above correctly permits the request; without this follow-on
        # selection the later apply operation could never find its own exact
        # run/ref while the four older PREPARED receipts remain untouched.
        #
        # This only selects an existing ledger. Exact run/ref, a fresh
        # Guard decision, owner TTY, source policy and stage/readback remain
        # independently mandatory in the apply path.
        if len(active) > 1 and all(record.status == "PREPARED"
                                   for _, record in active):
            successors = []
            for path, record in active:
                history = getattr(record, "history", None)
                if type(history) is not list or len(history) < 2:
                    continue
                previous, latest = history[-2:]
                if (type(previous) is not dict or type(latest) is not dict
                        or previous.get("status") != "VERIFIED"
                        or previous.get("path") != "m1-operator"
                        or previous.get("release_scope_ref") == record.release_scope_ref
                        or type(previous.get("generation")) is not int
                        or type(record.generation) is not int
                        or record.generation != previous["generation"] + 1
                        or record.previous_endpoint != previous.get("candidate_endpoint")
                        or type(previous.get("updated_at")) not in (int, float)
                        or not math.isfinite(previous["updated_at"])
                        or previous["updated_at"] <= 0
                        or type(record.updated_at) not in (int, float)
                        or not math.isfinite(record.updated_at)
                        or record.updated_at <= previous["updated_at"]
                        or any(type(other.updated_at) not in (int, float)
                               or not math.isfinite(other.updated_at)
                               or other.updated_at >= record.updated_at
                               for _, other in active if other is not record)):
                    continue
                if scope is not None and (
                        record.release_scope_ref != scope.scope_ref
                        or record.release_scope != scope.as_dict()):
                    continue
                # Only an intact predecessor scope may be used for live
                # attestation. The latest entry is already checked above;
                # earlier generations are not, so validate this one here.
                if (type(previous.get("release_scope")) is not dict
                        or type(previous.get("release_scope_ref")) is not str
                        or type(previous.get("candidate_authority")) is not str):
                    continue
                try:
                    previous_scope = ImmutableReleaseScope(
                        **previous["release_scope"])
                except (TypeError, ValueError):
                    continue
                if (previous_scope.scope_ref != previous["release_scope_ref"]
                        or previous_scope.candidate_authority
                           != previous["candidate_authority"]
                        or previous.get("release_scope_ref")
                           != previous_scope.scope_ref):
                    continue
                # Reuse the already trusted current-source verification.
                # It binds physical staged source, loaded launchd argument,
                # process PID and API, not a claimed journal status.
                predecessor = SimpleNamespace(**previous)
                if self.verified_current_release(predecessor) is True:
                    successors.append(path)
            if len(successors) == 1:
                self.superseded_prepared_count = len(active) - 1
                return successors[0]
        if len(active) > 1:
            # Preserve the fail-closed ambiguity, but make the owner review
            # actionable without opening/rewriting any prior release ledger.
            # Every record above has passed exact schema, scope and owner
            # file validation. Raw paths and Guard request identifiers stay
            # private. Bounded records expose only exact opaque scope digests.
            visible = sorted((record for _, record in active),
                             key=lambda row: (row.status, row.release_scope_ref))
            expected = scope.as_dict() if scope is not None else None
            summary = {
                "total": len(active),
                "prepared": sum(row.status == "PREPARED" for row in visible),
                "cutover": sum(row.status == "CUTOVER" for row in visible),
                "records": [
                    {"state": row.status,
                     "scope_ref": row.release_scope_ref,
                     "candidate_commit": row.candidate_authority.removeprefix(
                         "github-commit:"),
                     "matches_current_candidate": (
                         row.release_scope == expected if expected is not None
                         else None)}
                    for row in visible[:12]],
                "truncated": len(visible) > 12,
                "service_mutations": 0,
            }
            raise OperatorHostDenied("RELEASE_MULTIPLE_INFLIGHT",
                                     safe_contention=summary)
        if active:
            if scope is None:
                scope, observation = operator_only_release_scope(
                    home=self.home, root=self.source_root, git_run=self.git_run)
                if scope is None or observation.get("status") != "OBSERVED":
                    raise OperatorHostDenied("RELEASE_INFLIGHT_SCOPE_MISMATCH")
            path, record = active[0]
            if (record.release_scope_ref != scope.scope_ref
                    or record.release_scope != scope.as_dict()):
                raise OperatorHostDenied("RELEASE_INFLIGHT_SCOPE_MISMATCH")
            return path
        verified = [(path, record) for path, record in records if record.status == "VERIFIED"]
        if verified:
            try:
                installed = plistlib.loads(_owned_regular_bytes(self.plist, max_bytes=32768))
                args = installed.get("ProgramArguments")
                if (installed.get("Label") != LABEL or type(args) is not list
                        or any(type(arg) is not str for arg in args)):
                    raise ValueError("invalid installed definition")
            except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
                raise OperatorHostDenied("VERIFIED_INCUMBENT_UNIDENTIFIED") from None
            # This is a cheap rejection filter, never acceptance evidence.
            # Exact source/manifest/launchd/environment/PID/API verification
            # still runs for every ledger naming the actual candidate path.
            matching = [(path, record) for path, record in verified if args.count(str(
                self.home / "Library/Application Support/AI-Foundation/operator-release-staging"
                / record.release_scope_ref / "candidate/scripts/operator_server.py")) == 1]
        else:
            matching = []
        loaded = [path for path, record in matching
                  if self.verified_current_release(record) is True]
        if len(loaded) > 1:
            raise OperatorHostDenied("RELEASE_MULTIPLE_VERIFIED_LOADED")
        if verified and not loaded:
            raise OperatorHostDenied("VERIFIED_INCUMBENT_UNIDENTIFIED")
        return loaded[0] if loaded else primary

    def diagnose_current_release(self, prior):
        """Bounded, no-effect explanation for an installed VERIFIED predecessor.

        The registry alone cannot prove that the incumbent staged source is
        still the process bound to launchd. Never echo paths, data or errors.
        """
        try:
            scope_ref = prior.release_scope_ref
            authority = prior.candidate_authority
            if (prior.status != "VERIFIED"
                    or type(scope_ref) is not str
                    or re.fullmatch(r"[a-f0-9]{64}", scope_ref) is None
                    or type(authority) is not str
                    or re.fullmatch(r"github-commit:[a-f0-9]{40}", authority) is None):
                return "PREDECESSOR_IDENTITY_INVALID"
            prior_stage = (self.home / "Library/Application Support/AI-Foundation"
                           / "operator-release-staging" / scope_ref)
            try:
                present = prior_stage.lstat()
            except OSError:
                return "PREDECESSOR_STAGE_NOT_FOUND"
            if not stat.S_ISDIR(present.st_mode) or prior_stage.is_symlink():
                return "PREDECESSOR_STAGE_UNTRUSTED"
            try:
                if verify_staged(prior_stage, scope_ref) is not True:
                    return "PREDECESSOR_STAGE_UNVERIFIED"
            except (OSError, ValueError, TypeError, KeyError, StagingDenied):
                return "PREDECESSOR_STAGE_UNVERIFIED"
            manifest = json.loads(_read_private(prior_stage / "manifest.json"))
            tracked = manifest.get("tracked")
            key = "scripts/operator_server.py"
            if (manifest.get("candidate_commit") != authority.removeprefix("github-commit:")
                    or type(tracked) is not dict or type(tracked.get(key)) is not str):
                return "PREDECESSOR_MANIFEST_MISMATCH"
            prior_script = prior_stage / "candidate" / key
            if _sha(_owned_regular_bytes(prior_script)) != tracked[key]:
                return "PREDECESSOR_SCRIPT_HASH_CHANGED"
            live_plist = _owned_regular_bytes(self.plist, max_bytes=32768)
            plist = plistlib.loads(live_plist)
            args = plist.get("ProgramArguments")
            if (plist.get("Label") != LABEL or type(args) is not list
                    or args.count(str(prior_script)) != 1):
                # The prior immutable release archive also preserved the
                # original LaunchAgent and source. Distinguish a verified
                # physical rollback from an unknown third runtime, without
                # changing Guard, restarting a service or trusting a status.
                if _sha(live_plist) == manifest.get("prior_plist_sha256"):
                    old_path = manifest.get("prior_entry_path")
                    if type(old_path) is str and old_path.startswith("/"):
                        if (_sha(_owned_regular_bytes(Path(old_path)))
                                == manifest.get("prior_entry_sha256")):
                            return "INSTALLED_PREVIOUS_OPERATOR_RESTORED"
                return "RUNNING_PLIST_NOT_PREDECESSOR"
            expected, _ = candidate_operator_plist(
                _read_private(prior_stage / "previous-launchagent.plist"),
                Path(manifest["prior_entry_path"]), prior_stage / "candidate",
                code_workspace=_verified_owner_code_workspace(self.home))
            if plist != plistlib.loads(expected):
                return "RUNNING_PLIST_NOT_PREDECESSOR"
            loaded = self._launch("print", self.target)
            if (loaded.returncode != 0 or type(loaded.stdout) is not str
                    or not _loaded_definition_match(loaded.stdout, plist)):
                return "LAUNCHD_RUNNING_COMMAND_UNVERIFIED"
            if self._pid_owned() is not True:
                return "RUNNING_PID_NOT_BOUND"
            if self._human() is None:
                return "RUNNING_OPERATOR_API_UNAVAILABLE"
            return "VERIFIED"
        except (OSError, ValueError, TypeError, KeyError, RuntimeError,
                StagingDenied, OperatorHostDenied, plistlib.InvalidFileException):
            return "PREDECESSOR_READBACK_UNVERIFIED"

    def verified_current_release(self, prior):
        return self.diagnose_current_release(prior) == "VERIFIED"

    def _directory(self, scope):
        return self.home/"Library/Application Support/AI-Foundation/operator-release-staging"/scope.scope_ref

    def backup_prior(self, scope):
        if self.current_scope_ref() != scope.scope_ref:
            raise OperatorHostDenied("SCOPE_CHANGED_BEFORE_BACKUP")
        saved = stage_operator_only(self.source_root, self.home, git_run=self.git_run)
        if saved["scope_ref"] != scope.scope_ref or not saved["backup_verified"]:
            raise OperatorHostDenied("STAGE_IDENTITY_MISMATCH")
        self.stage = self._directory(scope)
        self.expected_scope = scope.scope_ref

    def _rollback_material(self, scope):
        # Corruption of the *candidate* cannot prevent restoring the prior
        # Operator. This validates old assets independently of new files.
        if self.stage != self._directory(scope) or self.expected_scope != scope.scope_ref:
            raise OperatorHostDenied("STAGE_NOT_HOST_OWNED")
        if (self.stage.is_symlink() or not self.stage.is_dir()
                or self.stage.stat().st_uid != os.getuid()
                or self.stage.stat().st_mode & 0o077):
            raise OperatorHostDenied("PRIVATE_STAGE_UNTRUSTED")
        manifest=json.loads(_read_private(self.stage/"manifest.json"))
        if manifest.get("schema") != 1 or manifest.get("scope_ref") != scope.scope_ref:
            raise OperatorHostDenied("ROLLBACK_MANIFEST_MISMATCH")
        old_plist=_read_private(self.stage/"previous-launchagent.plist")
        old_entry=_read_private(self.stage/"previous-operator-entry.py")
        if (_sha(old_plist) != manifest.get("prior_plist_sha256")
                or _sha(old_entry) != manifest.get("prior_entry_sha256")):
            raise OperatorHostDenied("ROLLBACK_BACKUP_MISMATCH")
        return manifest,old_plist

    def _manifest(self, scope):
        if self.stage != self._directory(scope) or self.expected_scope != scope.scope_ref:
            raise OperatorHostDenied("STAGE_NOT_HOST_OWNED")
        if verify_staged(self.stage, scope.scope_ref) is not True:
            raise OperatorHostDenied("PRIVATE_STAGE_UNVERIFIED")
        return json.loads(_read_private(self.stage/"manifest.json"))

    def verify_backup(self, scope):
        try:
            m = self._manifest(scope)
            old = _owned_regular_bytes(self.plist, max_bytes=32768)
            entry = Path(m["prior_entry_path"])
            source = _owned_regular_bytes(entry)
            return (_sha(old) == m["prior_plist_sha256"]
                    and _sha(source) == m["prior_entry_sha256"])
        except (OSError, KeyError, TypeError, ValueError, StagingDenied):
            return False

    def stage_candidate(self, scope):
        if not self.verify_backup(scope):
            raise OperatorHostDenied("PREVIOUS_OPERATOR_BACKUP_UNVERIFIED")
        manifest = self._manifest(scope)
        old_script = Path(manifest["prior_entry_path"])
        code_workspace = _verified_owner_code_workspace(self.home)
        self.candidate_definition, self.candidate_script = candidate_operator_plist(
            _read_private(self.stage/"previous-launchagent.plist"),
            old_script, self.stage/"candidate", code_workspace=code_workspace)

    def verify_candidate(self, scope):
        try:
            if not self.verify_backup(scope):
                return False
            manifest = self._manifest(scope)
            if self.candidate_definition is None:
                return False
            return (str(self.stage/"candidate/scripts/operator_server.py")
                    == self.candidate_script
                    and manifest["candidate_commit"] == scope.candidate_authority.removeprefix("github-commit:")
                    and _sha(_read_private(self.stage/"candidate/scripts/operator_server.py"))
                        == manifest["tracked"]["scripts/operator_server.py"])
        except (OSError, ValueError, KeyError, TypeError, StagingDenied):
            return False

    def _launch(self, *args):
        result = subprocess.run(["/bin/launchctl", *args],
                                capture_output=True, text=True, timeout=25)
        return result

    def _registered(self):
        return self._launch("print", self.target).returncode == 0

    def _await_unregistered(self):
        """launchctl bootout may return before launchd releases the label.

        Two consecutive absent observations are required. This is bounded:
        no new bootout and no service change during polling.
        """
        absent = 0
        for n in range(60):
            absent = absent + 1 if not self._registered() else 0
            if absent >= 2:
                return True
            if n != 59:
                time.sleep(.25)
        return False

    def _bootstrap_settled(self, *, rollback=False):
        """Retry ONLY a recognized transitional launchd error while absent.

        Do not treat arbitrary launchctl errors as transient, and never
        bootout a service just to retry bootstrap. One bounded attempt group
        belongs to the exact Guard-authorized cutover transaction.
        """
        error = ("ROLLBACK_BOOTSTRAP_REJECTED"
                 if rollback else "OPERATOR_BOOTSTRAP_REJECTED")
        for attempt in range(10):
            result = self._launch(
                "bootstrap", f"gui/{os.getuid()}", str(self.plist))
            if result.returncode == 0:
                return
            detail = result.stderr if isinstance(result.stderr, str) else ""
            transient = re.search(
                r"\b(?:5|37):\s*(?:Input/output error|Operation already in progress)\b",
                detail, re.IGNORECASE)
            if transient:
                if self._registered():
                    raise OperatorHostDenied(error + "_LABEL_PRESENT")
                if attempt == 9:
                    raise OperatorHostDenied(error + "_RETRY_EXHAUSTED")
                time.sleep(.75)
                continue
            # This categorizes a known denial without leaking launchctl stderr.
            # The raw macOS message never crosses the owner CLI boundary.
            if re.search(r"\b(?:Operation not permitted|Permission denied)\b",
                         detail, re.IGNORECASE):
                raise OperatorHostDenied(error + "_PERMISSION")
            raise OperatorHostDenied(error)
        raise OperatorHostDenied(error)

    def _pid_owned(self):
        row = self._launch("print", self.target)
        if row.returncode:
            return False
        found = re.search(r"^\s*pid = (\d+)\s*$", row.stdout, re.M)
        if not found:
            return False
        pid = int(found.group(1))
        cp = subprocess.run(["/usr/sbin/lsof","-nP","-t",
                             "-iTCP:8766","-sTCP:LISTEN"],
                            capture_output=True,text=True,timeout=7)
        return cp.returncode == 0 and cp.stdout.split() == [str(pid)]

    def _human(self):
        connection = http.client.HTTPConnection("127.0.0.1",PORT,timeout=3)
        try:
            connection.request("GET","/api/human",headers={"Host":"127.0.0.1"})
            response=connection.getresponse()
            if response.status != 200:
                return None
            data=response.read(HTTP_LIMIT+1)
            if len(data)>HTTP_LIMIT:
                return None
            obj=json.loads(data)
            return obj if type(obj) is dict else None
        except (OSError,ValueError,http.client.HTTPException):
            return None
        finally:
            connection.close()

    def _atomic_plist(self, data):
        current=self.plist.lstat()
        if (not stat.S_ISREG(current.st_mode)
                or current.st_uid != os.getuid()
                or current.st_mode & 0o022):
            raise OperatorHostDenied("OPERATOR_PLIST_OWNER_CHANGED")
        exact_mode=stat.S_IMODE(current.st_mode)
        fd,temp=tempfile.mkstemp(prefix=".operator-p4-",dir=self.plist.parent)
        try:
            with os.fdopen(fd,"wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(temp,exact_mode)
            os.replace(temp,self.plist)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def switch_operator(self, scope):
        if self.verify_candidate(scope) is not True:
            raise OperatorHostDenied("PINNED_CANDIDATE_REQUIRED")
        if self.current_scope_ref() != scope.scope_ref:
            raise OperatorHostDenied("LAST_MOMENT_SOURCE_CHANGE")
        live=self._human()
        if (not self._pid_owned() or live is None
                or not isinstance(live.get("activity"),list)
                or live["activity"]):
            raise OperatorHostDenied("OPERATOR_BUSY_OR_NOT_PID_BOUND")
        if self._launch("bootout",self.target).returncode:
            raise OperatorHostDenied("OPERATOR_BOOTOUT_REJECTED")
        if not self._await_unregistered():
            raise OperatorHostDenied("OPERATOR_BOOTOUT_SETTLE_TIMEOUT")
        self._atomic_plist(self.candidate_definition)
        self._bootstrap_settled()

    def readback_operator(self, scope):
        if self.candidate_definition is None or self.plist.read_bytes() != self.candidate_definition:
            return False
        try:
            # Revalidate actual staged bytes after bootstrap; a changed source
            # must trigger rollback even if an HTTP endpoint claims healthy.
            manifest=self._manifest(scope)
            if manifest.get("candidate_commit") != scope.candidate_authority.removeprefix("github-commit:"):
                return False
        except (OSError, ValueError, TypeError, KeyError, StagingDenied, OperatorHostDenied):
            return False
        for _ in range(40):
            if self._pid_owned():
                data = self._human()
                if (data is not None and type(data.get("development")) is dict
                        and data["development"].get("humanmodel_factory_registered") is True):
                    candidate = plistlib.loads(self.candidate_definition)
                    binding = candidate.get("EnvironmentVariables", {}).get(
                        "AI_FOUNDATION_REPO_ROOT")
                    if binding is None:
                        return True
                    services = data.get("services")
                    if (type(services) is list and any(
                            type(row) is dict
                            and row.get("name") == "TOOLHIVE CODE"
                            and row.get("ok") is True for row in services)):
                        return True
            time.sleep(.5)
        return False

    def rollback_operator(self, scope):
        manifest,original=self._rollback_material(scope)
        # If a failed switch never replaced the incumbent service, do not
        # disrupt a healthy original Operator merely to report rollback.
        if (self.plist.read_bytes() == original
                and self._pid_owned() and self._human() is not None):
            return
        if self._registered() and self._launch("bootout",self.target).returncode:
            raise OperatorHostDenied("ROLLBACK_BOOTOUT_REJECTED")
        if not self._await_unregistered():
            raise OperatorHostDenied("ROLLBACK_BOOTOUT_SETTLE_TIMEOUT")
        self._atomic_plist(original)
        self._bootstrap_settled(rollback=True)

    def verify_rollback(self, scope):
        try:
            manifest,_=self._rollback_material(scope)
            if _sha(_owned_regular_bytes(self.plist,max_bytes=32768)) != manifest["prior_plist_sha256"]:
                return False
            if _sha(_owned_regular_bytes(Path(manifest["prior_entry_path"]))) != manifest["prior_entry_sha256"]:
                return False
            for _ in range(30):
                if self._pid_owned() and self._human() is not None:
                    return True
                time.sleep(.5)
        except (OSError, ValueError, KeyError, TypeError, StagingDenied):
            pass
        return False


