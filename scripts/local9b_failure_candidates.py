"""Observed failed fixed test -> deduplicated diagnostic Issue with acceptance pins."""
import hashlib,json,subprocess,re
from pathlib import Path
from local9b_task_recipe import FixedPytest

REPO="quest7070-dev/AI-Foundation"
READY_LABEL="foundation-autodev:ready"
# Accepted host-owned, finite routine code/test pairs. This is the scope of
# the owner's standing development delegation, not a model-defined authority.
# Native, Guard, credentials, Operator effects and personal originals excluded.
DELEGATED_MAIN_PAIRS=frozenset({
    ("src/ai_foundation/notification_boundary.py","tests/test_notification_boundary.py"),
    ("src/ai_foundation/task_result.py","tests/test_task_result.py"),
    ("src/ai_foundation/question_bridge.py","tests/test_question_bridge.py"),
})

def standing_delegation(spec):
    """Only a newly observed main regression in exact predelegated scope.

    A consumed-model-attempt follow-up must always remain UNAPPROVED. Host
    reconstructs the prompt from fixed paths; GitHub/LLM prose cannot expand it.
    No new grant table, authority engine or user/profile inference is used.
    """
    if type(spec) is not dict or set(spec)!={"base","target","test","instruction"}:
        return False
    if spec["base"]!="main":
        return False
    pair=(spec["target"],spec["test"])
    if pair not in DELEGATED_MAIN_PAIRS:
        return False
    expected=("Repair the independently reproduced failure in "+pair[1]+
              " by changing only "+pair[0]+
              ". Preserve other behavior and all public APIs; do not change tests.")
    return type(spec["instruction"]) is str and spec["instruction"]==expected

def gh(*args):
    return subprocess.check_output(["/opt/homebrew/bin/gh",*args],text=True,timeout=30).strip()

def publish_candidate(spec,checkout,work):
    # Host rederives this fixed-test contract: model feedback selects NOTHING.
    sha=gh("api","repos/"+REPO+"/commits/"+spec["base"],"--jq",".sha")
    test=Path(checkout)/spec["test"]
    contract={"recipe":"python-fixed-test","base":spec["base"],"base_sha":sha,
        "target":spec["target"],"test":spec["test"],
        "test_sha256":hashlib.sha256(test.read_bytes()).hexdigest(),
        "instruction":spec["instruction"]}

    origin=spec.get("origin")
    origin_note=""
    if origin is not None:
        from local9b_failed_run_intake import (
            CANDIDATE_SCHEMA, REPAIRABLE, TASK_NAME, FAILURE_CLASSES)
        attempt=origin.get("attempt") if type(origin) is dict else None
        match=TASK_NAME.fullmatch(attempt) if type(attempt) is str else None
        if (type(origin) is not dict or origin.get("schema") != CANDIDATE_SCHEMA
                or type(origin.get("issue")) is not int or origin["issue"] < 1
                or origin.get("result_status") not in REPAIRABLE
                or type(origin.get("attempts")) is not int
                or not 1 <= origin["attempts"] <= 3
                or match is None or int(match.group(1)) != origin["issue"]
                or origin.get("approval_reusable") is not False
                or origin.get("original_base_sha") != contract["base_sha"]
                or origin.get("original_test_sha256") != contract["test_sha256"]
                or origin.get("failure_class") not in FAILURE_CLASSES
                or type(origin.get("feedback_sha256")) is not str
                or re.fullmatch(r"[0-9a-f]{64}", origin["feedback_sha256"]) is None):
            raise ValueError("INVALID_ORIGIN_ATTEMPT_RECEIPT")
        origin_note=("Original autonomous development Issue #"+
                     str(origin["issue"])+", outcome: "+origin["result_status"]+
                     " after "+str(origin["attempts"])+" bounded attempt(s). "+
                     "Observed failure class: "+origin["failure_class"]+
                     "; model feedback SHA256: "+origin["feedback_sha256"]+"."+
                     "\nThe original Issue was consumed and is NOT replayable. "+
                     "This follow-up is a distinct diagnostic proposal and "+
                     "requires a new explicit ready-label review.\n\n")

    runner=FixedPytest(contract,Path(checkout),Path(work))
    try:
        runner.run_tests("fixed")
    except RuntimeError as error:
        # Raw pytest output can contain private source lines and secrets even
        # when model feedback is omitted. Keep only bounded independent proof.
        failure_hash=hashlib.sha256(str(error).encode("utf-8")).hexdigest()
    else:
        raise ValueError("NO_CONFIRMED_TEST_FAILURE")
    # Independent fixed-test BASELINE failure is mandatory (above), as is an
    # exact current main checkout in FixedPytest. Only the finite standing
    # pairs may skip a per-Issue ready-label decision. No failed/consumed 9B
    # attempt reuses earlier approval, regardless of content similarity.
    delegated=origin is None and standing_delegation(spec)
    # The original ready candidate and its consumed-attempt follow-up must
    # never share a marker merely because their fixed test/target are equal.
    # Repeated publication of the SAME observed attempt is still idempotent.
    identity_payload=(contract if origin is None else {
        "contract":contract, "origin_attempt":origin["attempt"],
        "result_status":origin["result_status"],
        "feedback_sha256":origin["feedback_sha256"]})
    identity=hashlib.sha256(json.dumps(identity_payload,sort_keys=True).encode()).hexdigest()
    marker="<!-- local9b-failure:"+identity+" -->"
    matches=json.loads(gh("issue","list","--repo",REPO,"--state","all",
        "--search",identity,"--json","number,body","--limit","100"))
    if type(matches) is not list or len(matches)>=100:
        raise ValueError("CANDIDATE_DEDUP_COVERAGE_UNVERIFIED")
    for row in matches:
        if marker in (row.get("body") or ""):
            return {"status":"EXISTING","issue":row["number"]}
    body=(marker+"\n\n"+origin_note+"Observed fixed-test failure at "+sha+
        "\n\nTarget: "+spec["target"]+
        "\n\nSuccess criteria: the exact pinned test file must pass; "+
        "only the named source file may change. No merge or deployment.\n\n"+
        "Independent fixed-test failure digest (SHA256): "+
        failure_hash+" (raw test/model output omitted).\n\n"+
        "```foundation-autodev-task\n"+json.dumps(contract,sort_keys=True)+"\n```\n\n"+
        ("Standing host-bounded main-regression delegation: ready for one local 9B Draft-only attempt."
         if delegated else
         "Candidate only. The ready label is required separately before execution."))
    bodypath=Path(work)/"candidate-issue.md"
    bodypath.write_text(body)
    args=["issue","create","--repo",REPO,"--title",
          "Repair confirmed fixed-test failure: "+spec["target"],
          "--body-file",str(bodypath)]
    if delegated:
        args.extend(("--label",READY_LABEL))
    url=gh(*args)
    return {"status":"AUTO_READY" if delegated else "CREATED",
            "url":url,"contract":contract}


def collect_failure_candidates(root):
    from local9b_failed_run_intake import capture_failed_run_candidates
    reports=capture_failed_run_candidates(root)
    # Keep host-observed failure capture separate from Issue publication. The
    # publisher rechecks immutable base/test and can only create an unapproved
    # diagnostic Issue. No model generation or automatic ready label.
    for path in sorted((root/"failures").glob("*.json")):
        receipt=root/"results"/("candidate-"+path.name)
        if receipt.exists():continue
        # A stale/bad candidate cannot starve subsequent candidates forever.
        # Block its own source-bound item, retaining a nonprivate audit reason.
        try:
            spec=json.loads(path.read_text())
            if "test_output" in spec:
                spec=spec_from_error(spec)
            import tempfile
            with tempfile.TemporaryDirectory(prefix="failure-candidate-") as tmp:
                work=Path(tmp);checkout=work/"repo"
                subprocess.run(["/opt/homebrew/bin/gh","repo","clone",REPO,str(checkout),
                    "--","--depth","1","--branch",spec["base"]],check=True,timeout=90)
                result=publish_candidate(spec,checkout,work)
        except (OSError, RuntimeError, subprocess.CalledProcessError,
                subprocess.TimeoutExpired) as exc:
            # A transient clone/GitHub/backend failure is NOT a completed
            # publication. Preserve eligibility for the next scheduled tick,
            # but continue this tick so other candidates are not starved.
            reports.append({"status":"RETRYABLE","reason":type(exc).__name__})
            continue
        except (ValueError, KeyError, TypeError) as exc:
            code=str(exc)
            # The checked-out branch may have advanced before FixedPytest
            # independently reads its immutable base. A new tick can clone
            # the current branch; do not permanently consume this candidate.
            if isinstance(exc,ValueError) and code=="TASK_BASE_MOVED":
                reports.append({"status":"RETRYABLE","reason":"TASK_BASE_MOVED"})
                continue
            reason=(code if re.fullmatch(r"[A-Z][A-Z0-9_]{3,79}",code)
                    else type(exc).__name__)
            result={"status":"BLOCKED","reason":reason}
        receipt.write_text(json.dumps(result,indent=2));receipt.chmod(0o600);reports.append(result)
    return reports


def spec_from_error(event):
    """Infer only an unambiguous source/test pair from a host CI error event.

    No command or root-cause claim is taken from log prose. The candidate
    publisher must still reproduce the fixed test at the host-selected base.
    """
    if set(event)!={"base","test_output"} or type(event["test_output"]) is not str:
        raise ValueError("INVALID_TEST_ERROR_EVENT")
    log=event["test_output"]
    if len(log)>131072:raise ValueError("TEST_ERROR_EVENT_TOO_LARGE")
    sources=set(re.findall(r"(?<![A-Za-z0-9_])src/ai_foundation/[A-Za-z0-9_]+\.py",log))
    tests=set(re.findall(r"(?<![A-Za-z0-9_])tests/test_[A-Za-z0-9_]+\.py",log))
    if len(sources)!=1 or len(tests)!=1:
        raise ValueError("AMBIGUOUS_ERROR_SCOPE_NEEDS_REVIEW")
    target=next(iter(sources));test=next(iter(tests))
    return {"base":event["base"],"target":target,"test":test,
            "instruction":"Repair the independently reproduced failure in "+test+
                " by changing only "+target+
                ". Preserve other behavior and all public APIs; do not change tests."}


def _clone_standing_main(checkout):
    """Clone only the canonical main; never execute PR-head source."""
    subprocess.run(
        ["/opt/homebrew/bin/gh", "repo", "clone", REPO, str(checkout),
         "--", "--depth", "1", "--branch", "main"],
        check=True, timeout=90, stdout=subprocess.DEVNULL,
    )


def _checkout_standing_head(checkout):
    return subprocess.check_output(
        ["/usr/bin/git", "-C", str(checkout), "rev-parse", "HEAD"],
        text=True, timeout=10,
    ).strip()


def scan_standing_main_regressions(root, *, main_head=None,
                                    clone=None, checkout_head=None,
                                    publisher=None):
    """One bounded, model-free scan per main SHA in the existing 9B tick.

    Only the three *already owner-delegated* source/test pairs can publish an
    auto-ready Issue. publish_candidate re-fetches main, pins bytes, replays
    the fixed test under Seatbelt and refuses non-test/infrastructure failure.
    No general CI log, model output, secret or new grant can pick targets.

    A crash/uncertain GitHub acknowledgement preserves the exclusive claim,
    requiring reconciliation rather than blindly repeating an Issue effect.
    Optional injected functions are used only by source tests; the installed
    worker supplies no arguments except its existing owner-owned state root.
    """
    import os
    import tempfile
    from local9b_admission_handoff import _owned_existing_dir

    root = Path(root)
    inbox = _owned_existing_dir(root / "inbox")
    results = inbox.parent / "results"
    if main_head is None:
        main_head = gh("api", "repos/" + REPO + "/commits/main", "--jq", ".sha")
    if type(main_head) is not str or re.fullmatch(r"[a-f0-9]{40}", main_head) is None:
        return {"status": "BLOCKED", "reason": "MAIN_SHA_UNVERIFIED"}
    receipt = results / ("standing-main-" + main_head + ".json")
    claim = results / ("standing-main-" + main_head + ".claimed")
    if receipt.is_symlink() or claim.is_symlink():
        return {"status": "BLOCKED", "reason": "UNTRUSTED_SCAN_RECEIPT"}
    if receipt.exists():
        return {"status": "ALREADY_SCANNED", "main_sha": main_head}
    if claim.exists():
        return {"status": "RECONCILE_REQUIRED", "reason": "SCAN_CLAIM_UNCERTAIN",
                "main_sha": main_head}
    try:
        fd = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        return {"status": "RECONCILE_REQUIRED", "reason": "SCAN_ALREADY_CLAIMED",
                "main_sha": main_head}
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write('{"status":"SCANNING_UNVERIFIED"}\n')
        out.flush()
        os.fsync(out.fileno())

    clone = _clone_standing_main if clone is None else clone
    checkout_head = _checkout_standing_head if checkout_head is None else checkout_head
    publisher = publish_candidate if publisher is None else publisher
    checks = []
    phase = "PRE_PUBLISH"
    issued_in_this_scan = False
    try:
        with tempfile.TemporaryDirectory(prefix="standing-main-regression-") as tmp:
            checkout = Path(tmp) / "repo"
            clone(checkout)
            if checkout_head(checkout) != main_head:
                raise ValueError("TASK_BASE_MOVED")
            for target, test in sorted(DELEGATED_MAIN_PAIRS):
                spec = {"base": "main", "target": target, "test": test,
                        "instruction": ("Repair the independently reproduced failure in " +
                                        test + " by changing only " + target +
                                        ". Preserve other behavior and all public APIs; do not change tests.")}
                if not standing_delegation(spec):
                    raise ValueError("STANDING_DELEGATION_DRIFT")
                try:
                    phase = "PUBLISH_MAY_HAVE_STARTED"
                    outcome = publisher(spec, checkout, Path(tmp))
                except ValueError as error:
                    if str(error) == "NO_CONFIRMED_TEST_FAILURE":
                        # The publisher's fixed test ran but no Issue create
                        # was attempted. Allow a later clone/base drift to
                        # release this claim when no earlier Issue was made.
                        checks.append({"target": target, "status": "NO_REGRESSION"})
                        if not issued_in_this_scan:
                            phase = "PRE_PUBLISH"
                        continue
                    if str(error) == "TASK_BASE_MOVED" and not issued_in_this_scan:
                        # FixedPytest verifies the checkout before GitHub Issue
                        # search or creation. This error is pre-effect; do not
                        # strand the entire new-main scan forever.
                        phase = "PRE_PUBLISH"
                    raise
                if type(outcome) is not dict or outcome.get("status") not in ("AUTO_READY", "EXISTING"):
                    raise ValueError("STANDING_PUBLICATION_UNVERIFIED")
                if outcome["status"] == "AUTO_READY":
                    issued_in_this_scan = True
                elif not issued_in_this_scan:
                    # A preexisting deduped Issue is a read, not this scan's
                    # Issue creation. A later pre-effect error may safely retry.
                    phase = "PRE_PUBLISH"
                checks.append({"target": target, "status": outcome["status"]})
        record = {"status": "SCANNED", "main_sha": main_head, "checks": checks,
                  "model_calls": 0, "production_activated": False}
        # Same owner-only claim inode is atomically promoted to a durable scan
        # receipt after all independently checked targets have been considered.
        with claim.open("w", encoding="utf-8") as out:
            out.write(json.dumps(record, sort_keys=True) + "\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(claim, receipt)
        return record
    except Exception as error:
        # No external Issue effect has started: a source drift or clone error
        # can safely defer and retry on the next scheduled worker tick.
        if phase == "PRE_PUBLISH":
            try:
                claim.unlink()
            except OSError:
                return {"status": "RECONCILE_REQUIRED",
                        "reason": "PRE_EFFECT_CLAIM_CLEANUP_UNVERIFIED",
                        "main_sha": main_head}
            return {"status": "DEFERRED",
                    "reason": (str(error) if type(error) is ValueError and
                               re.fullmatch(r"[A-Z][A-Z0-9_]{3,79}", str(error))
                               else type(error).__name__),
                    "main_sha": main_head}
        # GitHub may already have created a ready Issue. Keep our claim
        # and demand reconciliation rather than blind replay.
        return {"status": "RECONCILE_REQUIRED",
                "reason": (str(error) if type(error) is ValueError and
                           re.fullmatch(r"[A-Z][A-Z0-9_]{3,79}", str(error))
                           else type(error).__name__),
                "main_sha": main_head}


def discovered_contract(base, target, test, source_sha, test_sha):
    """Immutable observation identity, not execution authority."""
    if (not re.fullmatch(r"[a-f0-9]{40}", base)
            or not re.fullmatch(r"src/ai_foundation/[A-Za-z0-9_]+\.py", target)
            or not re.fullmatch(r"tests/test_[A-Za-z0-9_]+\.py", test)
            or any(not re.fullmatch(r"[a-f0-9]{64}", x)
                   for x in (source_sha, test_sha))):
        raise ValueError("DISCOVERY_SOURCE_PINS_INVALID")
    digest = hashlib.sha256(json.dumps([base,target,test,source_sha,test_sha],
                                      separators=(",", ":")).encode()).hexdigest()
    instruction = ("Repair the independently reproduced regression in " + test
                   + " by changing only " + target
                   + ". Keep the fixed test unchanged and preserve public APIs. "
                   + "Exact base " + base + "; source " + source_sha
                   + "; test " + test_sha + ".")
    return "discovered-" + digest[:36], instruction


def discover_work_regression(repo, work, *, source_main, scope_current,
                             storage, submit):
    """One idle-cycle, offline fixed-test observation; same owner Work store.

    Only exact current main, public ordinary source/test pairs and an ACTIVE
    original Guard scope are eligible. A historic consumed attempt is not
    discovery evidence. Legacy standing pairs stay with their existing worker.
    """
    import tempfile
    from ai_foundation.orchestration import WorkStatus
    from ai_foundation.sensitive_input_scan import contains_sensitive_value
    from m1_development_review_candidate import _tracked_file
    from m1_development_ticket_factory import _git
    from m1_development_scope_delegation import _PROTECTED

    if scope_current() is not True:
        return None
    repo = Path(repo).resolve(strict=True)
    if (_git(repo,"rev-parse","HEAD") != source_main
            or _git(repo,"status","--porcelain","--untracked-files=all")):
        return {"state":"DISCOVERY_BASE_REVIEW_REQUIRED","execution_started":False}
    tracked = set(_git(repo,"ls-files","--","src/ai_foundation","tests").splitlines())
    pairs = []
    for target in sorted(tracked):
        if not re.fullmatch(r"src/ai_foundation/[A-Za-z0-9_]+\.py",target):
            continue
        stem = Path(target).stem
        test = "tests/test_"+stem+".py"
        if (test not in tracked or (target,test) in DELEGATED_MAIN_PAIRS
                or any(stem.startswith(prefix) for prefix in _PROTECTED)):
            continue
        identity = hashlib.sha256((source_main+"\0"+target+"\0"+test).encode()).hexdigest()
        pairs.append(("development-discovery:"+identity,target,test))
    if len(pairs)>1024:
        return {"state":"DISCOVERY_INVENTORY_UNVERIFIED","execution_started":False}
    chosen = None
    for i in range(0,len(pairs),100):
        window=pairs[i:i+100]
        observed=work.load_many(item[0] for item in window)
        for item in window:
            step=observed.get(item[0],())
            if not step or (len(step)==1 and step[0].status is WorkStatus.PLANNED):
                chosen=item
                break
        if chosen is not None:break
    if chosen is None:
        return None
    job,target,test=chosen
    storage.require("self-development discovery")
    work.ensure(job,["development-discovery"])
    if not work.transition(job,0,WorkStatus.PLANNED,WorkStatus.RUNNING,""):
        return {"state":"DISCOVERY_IN_PROGRESS","execution_started":False}
    def finish(state, *, failure=False, **extra):
        receipt={"state":state,"base_sha":source_main,"target":target,"test":test,**extra}
        if not work.transition(job,0,WorkStatus.RUNNING,
                               WorkStatus.FAILED if failure else WorkStatus.VERIFIED,
                               json.dumps(receipt,sort_keys=True)):
            return {"state":"DISCOVERY_READBACK_REQUIRED","execution_started":False}
        return {"state":state,"execution_started":False,**extra}
    phase = "SOURCE_PINS"
    try:
        source_sha = _tracked_file(repo,target)
        test_sha = _tracked_file(repo,test)
        if any(contains_sensitive_value((repo/name).read_text(encoding="utf-8"))
               for name in (target,test)):
            return finish("DISCOVERY_EXCLUDED_SENSITIVE")
        ticket,instruction=discovered_contract(source_main,target,test,source_sha,test_sha)
        if scope_current() is not True:
            return finish("DISCOVERY_SCOPE_INACTIVE",failure=True)
        phase = "ISOLATED_CHECKOUT"
        with tempfile.TemporaryDirectory(prefix="foundation-scoped-discovery-") as tmp:
            # macOS TMPDIR commonly resolves /var to /private/var. Compare
            # canonical containment roots, not a lexical alias to that root.
            workspace=Path(tmp).resolve(strict=True)
            checkout=workspace/"repo"
            subprocess.run(["/usr/bin/git","-c","core.hooksPath=/dev/null","clone",
                            "--no-checkout","--shared","--",str(repo),str(checkout)],
                           check=True,timeout=90,capture_output=True)
            subprocess.run(["/usr/bin/git","-C",str(checkout),"-c","core.hooksPath=/dev/null",
                            "checkout","--detach",source_main],check=True,timeout=60,
                           capture_output=True)
            checkout=checkout.resolve(strict=True)
            phase = "CHECKOUT_SOURCE_PINS"
            if (_git(checkout,"rev-parse","HEAD")!=source_main
                    or _tracked_file(checkout,target)!=source_sha
                    or _tracked_file(checkout,test)!=test_sha):
                raise ValueError("DISCOVERY_CHECKOUT_CHANGED")
            task={"recipe":"python-fixed-test","base":"main","base_sha":source_main,
                  "target":target,"test":test,"test_sha256":test_sha,
                  "instruction":instruction}
            if scope_current() is not True:
                return finish("DISCOVERY_SCOPE_INACTIVE",failure=True)
            phase = "FIXED_TEST"
            try:
                FixedPytest(task,checkout,workspace).run_tests("fixed")
            except RuntimeError as error:
                # A sandbox/fixture/backend failure is never a repair target.
                # Require a real pytest assertion failure with the exact test.
                output=str(error)
                if (not re.search(r"\b[1-9][0-9]* failed\b",output)
                        or not re.search(r"(?:^|\n)FAILED\s+"
                                         +re.escape(test)+r"::",output)
                        or "AssertionError" not in output
                        or re.search(r"PermissionError|OSError|FileNotFoundError|"
                                     r"Operation not permitted|Permission denied|"
                                     r"ModuleNotFoundError|ImportError|ERROR at (?:setup|teardown)",
                                     output)):
                    return finish("DISCOVERY_FAILURE_CLASS_UNVERIFIED",failure=True)
                failure_digest=hashlib.sha256(output.encode()).hexdigest()
            else:
                return finish("DISCOVERY_NO_REGRESSION")
        phase = "SOURCE_SCOPE_READBACK"
        if (scope_current() is not True
                or _git(repo,"rev-parse","HEAD")!=source_main
                or _git(repo,"status","--porcelain","--untracked-files=all")
                or _tracked_file(repo,target)!=source_sha
                or _tracked_file(repo,test)!=test_sha):
            return finish("DISCOVERY_SOURCE_OR_SCOPE_CHANGED",failure=True)
        phase = "WORK_REQUEST"
        receipt=submit(ticket,instruction)
        if (receipt.get("ticket_id")!=ticket or receipt.get("instruction_sha256")
                !=hashlib.sha256(instruction.encode()).hexdigest()):
            return finish("DISCOVERY_REQUEST_READBACK_UNVERIFIED",failure=True)
        return finish("DISCOVERY_REQUEST_RECORDED",ticket_id=ticket,
                      failure_sha256=failure_digest)
    except Exception as error:
        # Preserve a bounded phase and exception family, never private paths,
        # commands, model logs or raw pytest output.
        kind = type(error).__name__
        if kind not in {"ValueError","RuntimeError","PermissionError","OSError",
                        "FileNotFoundError","CalledProcessError","TimeoutExpired",
                        "OperationalError","IntegrityError","TypeError"}:
            kind = "OTHER"
        return finish("DISCOVERY_PROBE_BLOCKED",failure=True,
                      phase=phase,error_type=kind)
