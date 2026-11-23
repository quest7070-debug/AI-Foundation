#!/usr/bin/env python3
"""One owner-only real, locally bound HumanModel View -> pinned M1 9B E2E.

No raw source/answer/evidence IDs/owner identity/paths leave this process.
This tests evidence-bound technical operation, NEVER agreement with the owner.
Uses the existing installed source binding, persisted Guard denial state and
Ollama on loopback; no data import, approval, cloud route or effectful tools.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
for path in ("src", "scripts", "experiments/human_model"):
    sys.path.insert(0, str(ROOT / path))

from ai_foundation.authority_manifest import verify as verify_authority
from ai_foundation.auto_agent import AutoCapabilityAgent
from ai_foundation.capability_request import CapabilityRequest
from ai_foundation.core import GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.human_model_context import (
    HumanModelContext, _source_reader, load_bindings,
)
from ai_foundation.productization import load_config
from ai_foundation.routed_agent_model import foundation_agent_model
from ai_foundation.store import SQLiteGuardStore
from m1_humanmodel_9b_synthetic_e2e import (
    OnlyPinnedLocalRoute, SyntheticLocal9B, wait_for_admission, admission,
)
import m1_development_bridge as bridge
import m1_human_model_activation_readiness as readiness

REPO = "quest7070-dev/AI-Foundation"
OWNER = "quest7070-debug"
WORKFLOW = "Foundation M1 HumanModel synthetic 9B E2E"
TITLE = "Foundation HumanModel 9B E2E: current approved view"
BODY = "<!-- foundation-humanmodel-real-view-9b:v1 -->"
MARKER = "<!-- foundation-humanmodel-real-view-9b-receipt:v1:"
QUESTION = (
    "Based only on the currently authorized HumanModel records, what documented "
    "owner priorities, decisions, conditions and uncertainties are supported? "
    "Give a provisional answer with original evidence citations; if owner "
    "intent is not evidenced, say it is unknown."
)


class GuardReadOnlyStore:
    """Read current Guard denial/budget state without any DB migration or write."""
    def __init__(self, path):
        self.path = Path(path)
        metadata = self.path.lstat()
        if (not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or metadata.st_mode & 0o022):
            raise PermissionError("OWNER_GUARD_STORE_NOT_TRUSTED")

    def _row(self, sql, params=()):
        uri = "file:" + quote(str(self.path.resolve()), safe="/") + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=3) as db:
            db.execute("PRAGMA query_only=ON")
            return db.execute(sql, params).fetchone()

    def spent(self):
        row = self._row("SELECT value FROM guard_meta WHERE key='spent'")
        if row is None or type(row[0]) is not int:
            raise ValueError("GUARD_BUDGET_UNKNOWN")
        return row[0]

    def is_cancelled(self, run_id):
        return self._row(
            "SELECT 1 FROM cancellations WHERE run_id=?", (run_id,)) is not None

    def is_approved(self, run_id):
        return self._row(
            "SELECT 1 FROM approvals WHERE run_id=?", (run_id,)) is not None


def exact_owner_event(event, live):
    issue = event.get("issue") if type(event) is dict else None
    return (type(issue) is dict and event.get("action") == "opened"
            and event.get("repository", {}).get("full_name") == REPO
            and event.get("sender", {}).get("login") == OWNER
            and type(issue.get("number")) is int and issue["number"] > 0
            and issue.get("state") == "open"
            and issue.get("user", {}).get("login") == OWNER
            and issue.get("title") == TITLE and issue.get("body") == BODY
            and type(live) is dict
            and all(live.get(k) == issue.get(k)
                    for k in ("number", "title", "body", "state"))
            and live.get("user", {}).get("login") == OWNER)


def installed_owner_binding():
    """Fail closed unless prior trusted operator binding and actual owner agree."""
    paths = readiness.installed_paths()
    roots = readiness.existing_ledger_roots()
    if paths is None or len(roots) != 1:
        raise PermissionError("EXACT_OWNER_VIEW_UNAVAILABLE")
    installed_script, data = paths
    # Re-read the exact validated native operator launcher for its config file.
    plist = Path.home() / "Library/LaunchAgents/dev.quest7070.ai-foundation.operator.plist"
    row = plistlib.loads(plist.read_bytes())
    args = row["ProgramArguments"]
    index = args.index("--config") + 1
    setting = Path(args[index])
    working = Path(row.get("WorkingDirectory", "/"))
    if not setting.is_absolute():
        setting = working / setting
    if setting.is_symlink() or ".." in setting.parts:
        raise PermissionError("UNTRUSTED_OPERATOR_CONFIG")
    config = load_config(setting)
    if Path(config.data_dir).resolve(strict=True) != data.resolve(strict=True):
        raise PermissionError("OWNER_CONFIG_MISMATCH")
    verified = verify_authority(data, config)
    if verified.get("established") is not True or verified.get("missing"):
        raise PermissionError("AUTHORITY_NOT_ESTABLISHED")
    docker = shutil.which("docker") or next(
        (candidate for candidate in ("/usr/local/bin/docker", "/opt/homebrew/bin/docker")
         if Path(candidate).is_file()), None)
    if docker is None:
        raise PermissionError("OWNER_SERVICE_UNAVAILABLE")
    account = readiness._owner_record(docker)
    owner = account.get("owner")
    if (account.get("count") != 1 or type(owner) is not str
            or re.fullmatch(r"[0-9a-fA-F]{24}", owner) is None):
        raise PermissionError("OWNER_RECORD_UNVERIFIED")
    binding = load_bindings(data / "human-model-bindings.json").get(owner)
    if (binding is None or len(binding.scopes) != 1
            or Path(binding.root).resolve(strict=True) != roots[0].resolve(strict=True)):
        raise PermissionError("APPROVED_VIEW_NOT_UNIQUE")
    store = GuardReadOnlyStore(data / config.guard_db)
    guard = GuardCore(GuardState(spent=store.spent()), store=store)
    return owner, binding, guard


def redacted_result(answer, diagnosis):
    """Only fixed result categories and bounded counters, no private text."""
    status = answer.get("status") if type(answer) is dict else None
    refs = answer.get("cited_evidence_ids") if type(answer) is dict else None
    count = len(refs) if type(refs) is list and len(refs) <= 12 else 0
    technically_valid = (
        status == "SIMULATED_PROVISIONAL"
        and answer.get("citation_reference_status") == "MATCHED_IDS_ONLY"
        and answer.get("execution_authority") is False
        and answer.get("owner_statement_verified") is False
        and count > 0
        and diagnosis.get("model_state") == "MODEL_REPLY_VALID"
        and diagnosis.get("model_calls") == 1
    )
    allowed_reason = {
        "NO_RELEVANT_OWNER_EVIDENCE", "NO_OWNER_EVIDENCE",
        "OWNER_ANSWER_WITHOUT_SOURCE_CITATION",
        "OWNER_SIMULATION_ROUTE_UNAVAILABLE",
        "UNSUPPORTED_EVIDENCE_CITATION",
        "APPROVED_VIEW_UNAVAILABLE", "VIEW_CHANGED_DURING_SIMULATION",
    }
    raw_reason = answer.get("reason") if type(answer) is dict else None
    # Coverage describes source retrieval, separately from answer/citation
    # acceptance. A rejected answer does not prove an incomplete scan; absent
    # or malformed observations remain unknown rather than becoming False.
    observed = answer if type(answer) is dict else {}
    source_scan = observed.get("source_scan_complete")
    selection = observed.get("evidence_selection_complete")
    omitted = observed.get("omitted_records")
    citation_failure = observed.get("citation_failure_kind")
    return {
        "status": ("LIVE_PRIVATE_VIEW_CITED_PROVISIONAL" if technically_valid
                   else "NOT_ACCEPTED"),
        "reason": ("EVIDENCE_ID_VERIFIED" if technically_valid else
                   raw_reason if raw_reason in allowed_reason else
                   "OWNER_ANSWER_NOT_VERIFIED"),
        "model_calls": diagnosis.get("model_calls", 0),
        "model_state": (diagnosis.get("model_state")
                        if diagnosis.get("model_state") in {
                            "MODEL_REPLY_VALID", "MODEL_FINISH_LENGTH",
                            "MODEL_TIMEOUT", "MODEL_IO_PENDING", "MODEL_REPLY_INVALID",
                            "MODEL_HTTP_OK", "MODEL_HTTP_4XX", "MODEL_HTTP_5XX",
                            "MODEL_TRANSPORT", "MODEL_TRANSPORT_OR_JSON",
                            "MODEL_FINISH_OTHER",
                        } else "MODEL_NOT_CALLED"),
        "cited_count": count,
        "citation_failure_kind": citation_failure if type(citation_failure) is str and citation_failure in {
            "MALFORMED_MARKER", "UNKNOWN_EVIDENCE_ID", "VIEW_REVISION_MISMATCH",
        } else "NOT_APPLICABLE",
        "source_scan_complete": source_scan if type(source_scan) is bool else None,
        "evidence_selection_complete": selection if type(selection) is bool else None,
        "omitted_records_present": omitted > 0 if type(omitted) is int and omitted >= 0 else None,
        "needs_review": answer.get("needs_review") is True if technically_valid else True,
        "owner_fidelity": "NOT_EVALUATED",
        "execution_authority": False,
        "private_content_exported": False,
    }


def real_view_answer(diagnosis):
    owner, binding, guard = installed_owner_binding()
    context = HumanModelContext(
        binding, _source_reader(ROOT), guard=guard, run_id="m1-real-owner-view-answer")
    endpoint = SyntheticLocal9B(diagnosis)
    model = foundation_agent_model(
        OnlyPinnedLocalRoute(),
        lambda _: (_ for _ in ()).throw(PermissionError("CLOUD_FORBIDDEN")),
        endpoint, local_required=True)
    agent = AutoCapabilityAgent(
        model, object(), CapabilityRequest(capability="CHAT", owner_id=owner),
        human_model_context=context, run_id="m1-real-owner-view-answer")
    # Internal model / source traces must never be emitted to Actions log.
    with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
        answer = agent.answer_owner_question(QUESTION, scope=binding.scopes[0])
    return redacted_result(answer, diagnosis)


def execute():
    if (platform.system() != "Darwin"
            or platform.machine() not in ("arm64", "aarch64")
            or os.getuid() != os.geteuid() or os.getuid() != 501
            or os.environ.get("GITHUB_REPOSITORY") != REPO
            or os.environ.get("GITHUB_WORKFLOW") != WORKFLOW
            or os.environ.get("GITHUB_EVENT_NAME") != "issues"
            or os.environ.get("GITHUB_ACTOR") != OWNER):
        raise PermissionError("OWNER_M1_WORKFLOW_REQUIRED")
    token = os.environ.get("GITHUB_TOKEN")
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not token or not path:
        raise PermissionError("OWNER_EVENT_REQUIRED")
    event = json.loads(Path(path).read_text())
    number = event.get("issue", {}).get("number")
    if type(number) is not int or number < 1:
        raise PermissionError("OWNER_ISSUE_REQUIRED")
    prefix = "/repos/" + REPO + "/issues/" + str(number)
    live = bridge._github_api("GET", prefix, token)
    if not exact_owner_event(event, live):
        raise PermissionError("OWNER_ISSUE_CHANGED")
    comments = bridge._github_api("GET", prefix + "/comments?per_page=100", token)
    if (type(comments) is not list or len(comments) >= 100
            or any(type(c) is dict and MARKER + str(number) + " -->" in c.get("body", "")
                   for c in comments)):
        raise PermissionError("ALREADY_EXECUTED_OR_UNBOUNDED")
    diagnosis = {"model_calls": 0, "model_state": "MODEL_NOT_CALLED"}
    try:
        gate = wait_for_admission(observe=admission)
        if gate not in ("READY_EXISTING_9B", "READY_SAFE_COLD_START_9B"):
            result = {"status": "BLOCKED", "reason": gate, "model_calls": 0}
        else:
            result = real_view_answer(diagnosis)
    except Exception:
        result = {"status": "NOT_ACCEPTED", "reason": "LOCAL_PRIVATE_VIEW_UNAVAILABLE",
                  "model_calls": diagnosis["model_calls"]}
    result.update({
        "schema": 1, "private_source_used": result["model_calls"] > 0,
        "no_private_content_export": True, "owner_fidelity_accepted": False,
        "model_calls": diagnosis["model_calls"],
    })
    bridge._github_api("POST", prefix + "/comments", token, {
        "body": MARKER + str(number) + " -->\n"
                + "M1 local-only approved owner View → pinned 9B (metadata only)\n\n"
                + "~~~json\n" + json.dumps(result, sort_keys=True) + "\n~~~",
    })
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "LIVE_PRIVATE_VIEW_CITED_PROVISIONAL" else 1


if __name__ == "__main__":
    raise SystemExit(execute())
