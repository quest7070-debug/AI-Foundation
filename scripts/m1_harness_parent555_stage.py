#!/usr/bin/env python3
"""One-shot real M1 local9B Harness decomposition for *approved* parent #555.

Reuse existing P4 pinned DSH/Seatbelt/9B store, owner-limited compute lease
and the PR #524 frozen plan runtime. This is NOT a scheduler or a generic
command adapter. Stage one immutable plan; never label/create Issues here.
No paid model, 4B, main merge, Native signal or shared Ollama termination.
"""
from __future__ import annotations

from contextlib import nullcontext
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import time
from urllib import request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_foundation.development_harness_roles import (
    HarnessRoleRuntime, HostBoundHarnessAgent, verify_decomposition_proposal)
from ai_foundation.host_compute_lease import HostComputeLease, HostComputeBusy
from dev_autonomy_intake import GitHubAPI
from harness_decomposition_runtime import (
    REPO, SCHEMA, _digest, _load_plan_receipt, load_host_config,
    run_one, verify_host_baseline, verify_parent_scope)

HARNESS = Path(
    "/Volumes/StorageVolume/home-data/deepseek-harness-standalone/"
    "handoff/harness9b-contract-20261106")
PRIVATE = HARNESS / "private-dsh-home-stage-20261106"
OWNER_CONFIG = PRIVATE / "foundation-harness-parent555-config.json"
OWNER_PLAN = PRIVATE / "foundation-harness-parent555-plan.json"
BASE = "local9b/harness-two-source-red-20261110"
BASE_SHA = "b752bab66841ed0ee9f401bf12532132c003cb74"
MODEL_SHA = "56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90"
BUDGET = PRIVATE / "harness9b-autodev-16384-ctx32768.patch.yml"
STORE = (Path.home() /
         "Library/Application Support/AI-Foundation/direct-apfs-releases/"
         "ollama-qwen3-5-9b-56671c2ab9385f9c/models")
OLLAMA = Path("/opt/homebrew/Cellar/ollama/0.34.4/libexec/ollama")
# Process-local diagnostic only. Never persisted into a new owner state store.
# A failure after MODEL_HANDOFF is uncertain; it is never auto-replayed.
STAGE_PHASE = "PRECHECK"
MODEL_HANDOFF_ATTEMPTED = False


def reviewed_contracts():
    return {
        "src/ai_foundation/agent.py": {
            "test": "tests/test_local9b_harness_agent_output_boundary_20261110.py",
            "test_sha256": "31903380e59988dea0961f021ec58f9dc09cf36f6c6d5346bc44fcde67f5b144",
            "instruction": (
                "Reject absent None model output, never silently stringify it. "
                "Preserve normal string replies."),
        },
        "src/ai_foundation/development_loop.py": {
            "test": "tests/test_local9b_harness_acceptance_evidence_20261110.py",
            "test_sha256": "2eaaf0e5dac387687780b1178301689a82bce0900fa1a259bb145197d4926288",
            "instruction": (
                "If fixed test execution returns an empty acceptance result, "
                "do not publish Draft or report TESTED_CHANGE. Return "
                "TEST_ACCEPTANCE_UNVERIFIED, preserving valid passing delivery."),
        },
    }


def _owner_file(path, *, max_bytes=262144):
    if path.is_symlink() or not path.is_file():
        raise ValueError("OWNER_PINNED_FILE_MISSING")
    meta = path.lstat()
    if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid()
            or meta.st_mode & 0o022 or meta.st_size > max_bytes):
        raise ValueError("OWNER_PINNED_FILE_UNTRUSTED")
    raw = path.read_bytes()
    if len(raw) > max_bytes:
        raise ValueError("OWNER_PINNED_FILE_TOO_LARGE")
    return raw


def _store_exact_config(data: bytes) -> str:
    """Exclusive create or exact immutable re-read; no rewriting owner state."""
    if not PRIVATE.is_dir() or PRIVATE.is_symlink():
        raise ValueError("OWNER_PRIVATE_HOME_MISSING")
    meta = PRIVATE.stat()
    if meta.st_uid != os.getuid() or meta.st_mode & 0o022:
        raise ValueError("OWNER_PRIVATE_HOME_UNTRUSTED")
    if OWNER_CONFIG.exists() or OWNER_CONFIG.is_symlink():
        if _owner_file(OWNER_CONFIG) != data:
            raise ValueError("OWNER_CONFIG_PREVIOUS_VERSION_DRIFT")
        return _digest(data)
    fd = os.open(OWNER_CONFIG, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return _digest(data)


def _make_config(native, seatbelt, budget) -> dict:
    return {
        "schema": SCHEMA, "repository": REPO,
        "parent_issue": 555, "base": BASE, "base_sha": BASE_SHA,
        "reviewed_contracts": reviewed_contracts(),
        "harness": {
            "argv": ["/usr/bin/sandbox-exec", "-f", str(seatbelt),
                     str(native / "runtime/node_modules/.bin/dsh"),
                     "--profile", "headless", "--patch", str(budget)],
            "cwd": str(PRIVATE),
            "timeout_s": 900,
            "seatbelt_sha256": _digest(_owner_file(seatbelt, max_bytes=65536)),
            "patch_sha256": _digest(_owner_file(budget)),
        },
    }


def _tagged_models(port, endpoint):
    opener = request.build_opener(request.ProxyHandler({}))
    with opener.open(
            f"http://127.0.0.1:{port}/api/{endpoint}", timeout=4) as reply:
        if reply.status != 200:
            raise ValueError("LOCAL_OLLAMA_HTTP_UNAVAILABLE")
        return json.loads(reply.read(65536))


def _exclusive_port():
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", 11436))
        except OSError as exc:
            raise HostComputeBusy("EXISTING_LOCAL_BACKEND_PORT_BUSY") from exc


class DeferredCiNotGreen(Exception):
    pass


def _require_current_head_green(api):
    """No model inference competing with incomplete same-head Foundation CI."""
    head = os.environ.get("PR_HEAD_SHA", "")
    if len(head) != 40 or any(c not in "0123456789abcdef" for c in head):
        raise ValueError("OWNER_GITHUB_HEAD_NOT_PINNED")
    runs = api.request(api.repo_path(
        "/actions/runs?head_sha=" + head + "&per_page=40"))
    if type(runs) is not dict or type(runs.get("workflow_runs")) is not list:
        raise ValueError("CURRENT_FOUNDATION_CI_UNAVAILABLE")
    exact = [item for item in runs["workflow_runs"]
             if type(item) is dict and item.get("name") == "Foundation CI"
             and item.get("head_sha") == head]
    # A previous green run does not authorize model allocation while a newer
    # same-head CI is pending or has failed. GitHub run IDs are monotonic;
    # never trust API list order or a green result from a different commit.
    if not exact:
        raise DeferredCiNotGreen()
    if any(type(item.get("id")) is not int or item["id"] <= 0
           for item in exact):
        raise ValueError("CURRENT_FOUNDATION_CI_UNAVAILABLE")
    latest = max(exact, key=lambda item: item["id"])
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise DeferredCiNotGreen()


def _stage_one():
    global STAGE_PHASE, MODEL_HANDOFF_ATTEMPTED
    STAGE_PHASE = "PRECHECK"
    MODEL_HANDOFF_ATTEMPTED = False
    # Private modules already used by the accepted P4 worker. Never allow
    # Issue text, model output or any GitHub request to supply import paths.
    sys.path.insert(0, str(HARNESS / "experiments/harness9b"))
    from native_code_compare import (
        published_candidate, no_cloud_env, pinned_file,
        NATIVE_SEATBELT_NAME, NATIVE_SEATBELT_SHA)
    from native_fake_e2e import V6_PATCH_NAME, V6_PATCH_SHA256

    native, _ = published_candidate()
    STAGE_PHASE = "OWNER_PROFILE"
    seatbelt = PRIVATE / NATIVE_SEATBELT_NAME
    pinned_file(seatbelt, NATIVE_SEATBELT_SHA)
    pinned_file(PRIVATE / V6_PATCH_NAME, V6_PATCH_SHA256)
    if not (BUDGET.exists() and BUDGET.is_file()):
        raise ValueError("LOCAL9B_BUDGET_PROFILE_MISSING")
    profile = _owner_file(BUDGET)
    if (b"qwen3.5:9b" not in profile
            or b"http://127.0.0.1:11436/v1" not in profile
            or b"maxTokens: 16384" not in profile):
        raise ValueError("LOCAL9B_BUDGET_PROFILE_UNREVIEWED")
    config = _make_config(native, seatbelt, BUDGET)
    config_bytes = (json.dumps(config, sort_keys=True, ensure_ascii=False,
                               separators=(",", ":")) + "\n").encode()
    api = GitHubAPI(os.environ["GITHUB_TOKEN"], REPO)
    _require_current_head_green(api)
    STAGE_PHASE = "PARENT_BASELINE"
    # Every invocation, even a no-model existing plan, checks that the
    # original owner-approved Issue and exact source/test branch still match.
    scope = verify_host_baseline(api, config)
    verify_parent_scope(api, config, scope)
    STAGE_PHASE = "OWNER_STATE_RECONCILE"
    def reuse_plan():
        if not (OWNER_PLAN.exists() or OWNER_PLAN.is_symlink()):
            return None
        digest = _digest(_owner_file(OWNER_PLAN, max_bytes=65536))
        frozen = _load_plan_receipt(str(OWNER_PLAN), digest)
        verify_decomposition_proposal(
            frozen, issue_number=555, base_sha=BASE_SHA,
            reviewed_scope={k: v["test"] for k, v in scope.items()})
        return {"status": "ALREADY_STAGED", "plan_sha256": digest,
                "model_invoked": False, "execution_authorized": False}

    # A previous immutable plan is read-only; never need a new model turn.
    # A missing config alongside a previous plan is inconsistent, not a
    # reason to generate/overwrite owner receipt files.
    if OWNER_PLAN.exists() or OWNER_PLAN.is_symlink():
        if _owner_file(OWNER_CONFIG) != config_bytes:
            raise ValueError("OWNER_PLAN_WITH_DIFFERENT_CONFIG")
        load_host_config(str(OWNER_CONFIG), _digest(config_bytes))
        return reuse_plan()

    # The model-start path, INCLUDING exclusive config creation, is covered
    # by the existing compute lease. Busy means no file or model effects.
    with HostComputeLease().hold():
        config_sha = _store_exact_config(config_bytes)
        config = load_host_config(str(OWNER_CONFIG), config_sha)
        prior = reuse_plan()
        if prior is not None:
            return prior
        STAGE_PHASE = "COMPUTE_ADMISSION"
        if _tagged_models(11434, "ps").get("models") != []:
            raise HostComputeBusy("SHARED_OLLAMA_MODEL_BUSY")
        _exclusive_port()
        if not STORE.is_dir() or not OLLAMA.is_file():
            raise ValueError("PINNED_LOCAL9B_STORE_OR_EXECUTABLE_MISSING")
        if not (PRIVATE / "tmp").is_dir():
            raise ValueError("EXISTING_PRIVATE_TMP_UNAVAILABLE")

        sanitized = no_cloud_env(native)
        # No inherited API keys or cloud-provider fallback to the DSH child.
        safe = {key: value for key, value in sanitized.items()
                if key in {"PATH", "LANG", "LC_ALL", "TERM", "TMPDIR",
                           "OLLAMA_HOST", "OLLAMA_API_KEY"}}
        safe["HOME"] = str(PRIVATE)
        safe["DSH_HOME"] = str(PRIVATE)
        safe["OLLAMA_HOST"] = "127.0.0.1:11436"
        safe.setdefault("OLLAMA_API_KEY", "ollama")
        STAGE_PHASE = "DEDICATED_BACKEND"
        with tempfile.TemporaryDirectory(prefix="harness-parent555-",
                                         dir=PRIVATE / "tmp") as root:
            log = Path(root) / "owned-backend.log"
            with log.open("w") as out:
                out.flush()
                daemon = subprocess.Popen(
                    [str(OLLAMA), "serve"],
                    env={**safe, "OLLAMA_HOST": "127.0.0.1:11436",
                         "OLLAMA_MODELS": str(STORE), "OLLAMA_NUM_PARALLEL": "1",
                         "OLLAMA_MAX_LOADED_MODELS": "1",
                         "OLLAMA_CONTEXT_LENGTH": "32768"},
                    stdout=out, stderr=out, stdin=subprocess.DEVNULL)
                try:
                    for _ in range(50):
                        try:
                            tags = _tagged_models(11436, "tags")
                            if not any(row.get("name") == "qwen3.5:9b"
                                       and row.get("digest") == MODEL_SHA
                                       for row in tags.get("models", [])):
                                raise ValueError("PINNED_MODEL_IDENTITY_MISMATCH")
                            break
                        except (OSError, TimeoutError):
                            time.sleep(.2)
                    else:
                        raise ValueError("DEDICATED_BACKEND_UNAVAILABLE")
                    agent = HostBoundHarnessAgent(
                        tuple(config["harness"]["argv"]),
                        config["harness"]["cwd"], safe, 900)
                    roles = HarnessRoleRuntime({"decomposition": agent})
                    class BorrowedLease:
                        def hold(self):
                            return nullcontext()
                    STAGE_PHASE = "MODEL_HANDOFF"
                    MODEL_HANDOFF_ATTEMPTED = True
                    staged = run_one(
                        config, api, roles,
                        stage_plan_file=str(OWNER_PLAN),
                        owner_config_path=str(OWNER_CONFIG),
                        lease=BorrowedLease())
                    STAGE_PHASE = "PLAN_PERSISTED"
                    return {"status": staged["status"],
                            "plan_sha256": staged["plan_file_sha256"],
                            "proposal_sha256": staged["proposal_sha256"],
                            "number_of_children": len(staged["children"]),
                            "model_invoked": True,
                            "execution_authorized": False}
                finally:
                    # Only the child daemon started above, never the shared
                    # Ollama or a user's model. No SIGKILL or eviction.
                    daemon.terminate()
                    daemon.wait(timeout=15)


def _publish_and_admit_one():
    """Turn the one owner-pinned stage into one existing ready-Issue handoff.

    No inference, scheduler, new owner database, child-command generation or
    blanket ready grant. Exact parent #555, branch/test hashes and the staged
    proposal are independently reread before each GitHub effect.
    """
    global STAGE_PHASE, MODEL_HANDOFF_ATTEMPTED
    STAGE_PHASE = "CHILD_PREFLIGHT"
    MODEL_HANDOFF_ATTEMPTED = False
    api = GitHubAPI(os.environ["GITHUB_TOKEN"], REPO)
    _require_current_head_green(api)
    current = api.request(api.repo_path("/commits/main"))
    if (type(current) is not dict
            or current.get("sha") != os.environ.get("PR_HEAD_SHA")):
        raise ValueError("OWNER_MAIN_CHANGED_AFTER_TRIGGER")
    config_sha = _digest(_owner_file(OWNER_CONFIG))
    config = load_host_config(str(OWNER_CONFIG), config_sha)
    if (config.get("parent_issue") != 555 or config.get("base") != BASE
            or config.get("base_sha") != BASE_SHA
            or config.get("reviewed_contracts") != reviewed_contracts()):
        raise ValueError("PARENT555_HOST_SCOPE_DRIFT")
    proposal_sha = _digest(_owner_file(OWNER_PLAN, max_bytes=65536))
    proposal = _load_plan_receipt(str(OWNER_PLAN), proposal_sha)
    STAGE_PHASE = "CHILD_SOURCE_RECHECK"
    contracts = verify_host_baseline(api, config)
    verify_parent_scope(api, config, contracts)

    # Reuse the existing decomposition runtime's cross-call lock identity;
    # never publish/admit two children concurrently from the same host.
    lock_path = Path(str(OWNER_CONFIG) + ".publish.lock")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock_path, flags, 0o600)
    with os.fdopen(fd, "r+b") as lock:
        info = os.fstat(lock.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise ValueError("HOST_CHILD_LOCK_UNTRUSTED")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        STAGE_PHASE = "CHILD_PUBLICATION"
        # run_one handles each exact source/parent readback and creates at
        # most ONE unapproved Issue using the existing GitHub authority.
        published = run_one(config, api, None, proposal_receipt=proposal,
                            publish=True)
        STAGE_PHASE = "CHILD_ADMISSION"
        # Only dependency-free children with exact pinned parent-ready scope
        # can acquire the existing ready label. Worker still independently
        # verifies admission and only then performs one bounded 9B attempt.
        admitted = run_one(config, api, None, proposal_receipt=proposal,
                           admit=True)
    return {
        "status": "CHILD_HANDOFF_RECONCILED",
        "publication": published["status"],
        "admission": admitted["status"],
        "model_invoked": False,
        "worker_invoked": False,
        "draft_published": False,
    }


# The existing PR CI runner can wait modestly for another cooperating job
# to release its lease or for the shared Ollama model to become idle. The
# budget is bounded: no permanent runner occupation, second worker, or
# separate scheduler. 600s wait + <=900s DSH inference fits a 30min job.
MAX_STAGE_WAIT_S = 600
STAGE_POLL_S = 30


def _stage_when_available(*, max_wait_s=MAX_STAGE_WAIT_S,
                          poll_s=STAGE_POLL_S):
    """Retry *only* pre-model transient deferrals. Never retry uncertain work."""
    if (type(max_wait_s) is not int or not 0 <= max_wait_s <= 600
            or type(poll_s) is not int or not 1 <= poll_s <= 60):
        raise ValueError("INVALID_STAGE_RETRY_BOUNDS")
    deadline = time.monotonic() + max_wait_s
    attempt = 0
    while True:
        attempt += 1
        try:
            return _stage_one()
        except (HostComputeBusy, DeferredCiNotGreen) as exc:
            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0:
                raise
            pause = min(float(poll_s), remaining)
            status = ("WAIT_FOR_CI" if isinstance(exc, DeferredCiNotGreen)
                      else "WAIT_FOR_COMPUTE")
            print("HARNESS_PARENT555_WAIT=" + json.dumps({
                "status": status, "attempt": attempt,
                "remaining_seconds": round(remaining, 1),
                "model_invoked": False, "execution_authorized": False,
            }, sort_keys=True), flush=True)
            time.sleep(pause)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv not in (["--stage-one"], ["--publish-and-admit-one"]):
        raise SystemExit("EXACT_ONE_SHOT_STAGE_FLAG_REQUIRED")
    try:
        result = (_stage_when_available() if argv == ["--stage-one"]
                  else _publish_and_admit_one())
        print("HARNESS_PARENT555_STAGE=" +
              json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 0
    except DeferredCiNotGreen:
        print('HARNESS_PARENT555_STAGE={"status":"DEFERRED_CI_NOT_GREEN",'
              '"model_invoked":false,"execution_authorized":false}')
        return 0
    except HostComputeBusy:
        print('HARNESS_PARENT555_STAGE={"status":"DEFERRED_COMPUTE_BUSY",'
              '"model_invoked":false,"execution_authorized":false}')
        return 0
    except Exception as exc:
        # Return only explicitly allowlisted local stage codes, never source,
        # tool stderr, model text or private paths. Do not convert unknown
        # model outcomes into retryable admission failures.
        known_codes = {
            "HARNESS_ROLE_EXIT_NONZERO", "OWNER_CONFIG_PREVIOUS_VERSION_DRIFT",
            "HOST_BASE_SHA_MOVED", "HOST_PARENT_NOT_APPROVED",
            "HOST_PARENT_SCOPE_INVALID", "HOST_FIXED_TEST_SHA_DRIFT",
            "SHARED_OLLAMA_MODEL_BUSY", "DEDICATED_BACKEND_UNAVAILABLE",
            "PINNED_LOCAL9B_STORE_OR_EXECUTABLE_MISSING",
        }
        reason = str(exc) if str(exc) in known_codes else type(exc).__name__.upper()
        print("HARNESS_PARENT555_STAGE=" + json.dumps({
            "status": "BLOCKED",
            "reason": reason,
            "phase": STAGE_PHASE,
            "model_handoff_attempted": MODEL_HANDOFF_ATTEMPTED,
            "retry_authorized": False,
            "execution_authorized": False,
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
