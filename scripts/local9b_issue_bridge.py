"""Ready GitHub Issue → bounded host recipe; no model-selected commands."""
import hashlib
import json
import re
import subprocess

REPOSITORY="quest7070-dev/AI-Foundation"
READY_LABEL="foundation-autodev:ready"
FIELDS={"request_queue_size","max_concurrent_requests"}

def _gh(*args):
    return json.loads(subprocess.check_output(
        ["/opt/homebrew/bin/gh",*args],text=True,timeout=30))

def issue_task(issue, *, read_dependency=None):
    """The ready label authorizes only this exact supported finite recipe."""
    labels={x["name"] for x in issue.get("labels",[]) if type(x) is dict}
    if READY_LABEL not in labels or issue.get("state") not in ("OPEN","open"):
        raise ValueError("ISSUE_NOT_READY")
    body=issue.get("body") or ""
    blocks=re.findall(r"```foundation-autodev-task\s*\n(.*?)\n```",body,re.S)
    if len(blocks)!=1:raise ValueError("SCOPED_TASK_CONTRACT_REQUIRED")
    contract=json.loads(blocks[0])
    if type(contract) is not dict:
        raise ValueError("TASK_CONTRACT_NOT_OBJECT")
    base=contract.get("base")
    if (type(base) is not str or not re.fullmatch(r"(?:main|local9b/[A-Za-z0-9_./-]{1,140})",base) or ".." in base):
        raise ValueError("TASK_BASE_INVALID")
    generic=contract.get("recipe")=="python-fixed-test"
    if generic:
        from local9b_task_recipe import validate_contract
        validate_contract(contract)
    elif (set(contract)!={"recipe","base","field"} or
          contract["recipe"]!="bounded-http-positive-limit" or
          contract["field"] not in FIELDS):
        raise ValueError("UNSUPPORTED_TASK_CONTRACT")
    number=issue["number"]
    if type(number) is not int or number<1:raise ValueError("ISSUE_ID_INVALID")
    # Reuse the existing GitHub planer's dependency contract at execution
    # admission too. A ready child must not bypass incomplete parent steps.
    from github_task_orchestrator import metadata
    paths, depends_on=metadata(body, number)
    if generic and paths and paths != [contract["target"]]:
        raise ValueError("TASK_DECLARED_WRITE_SCOPE_MISMATCH")
    for dep in depends_on:
        previous=(read_dependency(dep) if read_dependency is not None else
                  _gh("issue","view",str(dep),"--repo",REPOSITORY,
                      "--json","number,state"))
        if (type(previous) is not dict or previous.get("number") != dep
                or previous.get("state") not in ("CLOSED","closed")):
            raise ValueError("TASK_DEPENDENCY_NOT_CLOSED")
    digest=hashlib.sha256(json.dumps(
        {"number":number,"body":body,"updatedAt":issue["updatedAt"]},
        sort_keys=True).encode()).hexdigest()
    return {"id":"issue-"+str(number)+"-"+digest[:16],
            "base":contract["base"],"field":contract.get("field","max_concurrent_requests"),
            **(contract if generic else {}),
            "source_issue":number,"source_digest":digest}

def previous_issue_attempt(inbox, issue_number):
    """An Issue is one bounded execution authorization, even after body edits.

    The worker creates an exclusive .started marker before effects; only an
    unconsumed HostComputeBusy removes it. A finished result also counts if the
    marker was subsequently lost. A new attempt needs a *new approved Issue*.
    This avoids replay after timeout, crash, Draft delivery or an Issue edit.
    """
    results = inbox.parent / "results"
    if results.is_symlink():
        raise ValueError("UNTRUSTED_RESULT_DIRECTORY")
    # Per-Issue exclusive claim closes concurrent-worker races between
    # checking a receipt and creating a task-specific .started marker.
    claim = results / ("issue-" + str(issue_number) + ".claimed")
    if claim.is_symlink():
        raise ValueError("UNTRUSTED_PRIOR_ATTEMPT")
    if claim.exists():
        if not claim.is_file():
            raise ValueError("UNTRUSTED_PRIOR_ATTEMPT")
        return True
    for suffix in (".started", ".json"):
        for path in results.glob("issue-" + str(issue_number) + "-*" + suffix):
            if path.is_symlink() or not path.is_file():
                raise ValueError("UNTRUSTED_PRIOR_ATTEMPT")
            return True
    return False


def collect_ready(inbox):
    from local9b_task_selection import admission, evidence, ordered_reports
    issues=_gh("issue","list","--repo",REPOSITORY,"--state","open",
        "--label",READY_LABEL,"--limit","100",
        "--json","number,body,labels,state,updatedAt")
    if len(issues)>=100:raise ValueError("ISSUE_SCAN_LIMIT_REACHED")
    report=[]
    for issue in issues:
        try:
            decision=admission(issue)
            if decision["status"] != "ELIGIBLE":
                report.append({"issue":issue.get("number"), **decision})
                continue
            task=issue_task(issue)
            if previous_issue_attempt(inbox, issue["number"]):
                report.append({"issue":issue["number"],
                               "status":"ALREADY_ATTEMPTED",
                               "reason":"Prior start/result receipt; new work requires a new approved Issue"})
                continue
            path=inbox/(task["id"]+".json")
            if not path.exists():
                # Exclusive creation prevents replacement of a queued task.
                with path.open("x") as f:json.dump(task,f)
                path.chmod(0o600)
            report.append({"issue":issue["number"],"task":task["id"],
                           **decision, **evidence(task), "status":"QUEUED"})
        except (ValueError,KeyError,TypeError) as e:
            report.append({"issue":issue.get("number"),"status":"NEEDS_SCOPED_CONTRACT","reason":str(e)[:120]})
    return ordered_reports(report)

def resolve_task(task):
    legacy={"id":"http-request-queue-positive-20261107",
            "base":"local9b/bounded-http-positive-limit-1793997731",
            "field":"request_queue_size"}
    if task==legacy:return task
    if type(task) is not dict or type(task.get("source_issue")) is not int:
        raise ValueError("TASK_HAS_NO_APPROVED_ISSUE")
    issue=_gh("issue","view",str(task["source_issue"]),"--repo",REPOSITORY,
              "--json","number,body,labels,state,updatedAt")
    from local9b_task_selection import admission
    if admission(issue)["status"] != "ELIGIBLE":
        raise ValueError("ISSUE_SELECTION_POLICY_CHANGED")
    if issue_task(issue)!=task:raise ValueError("ISSUE_APPROVAL_OR_CONTRACT_CHANGED")
    return task
