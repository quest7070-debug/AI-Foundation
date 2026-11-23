#!/usr/bin/env python3
"""Read-only, event-driven GitHub task discovery for Foundation."""
from __future__ import annotations
import argparse, json, os, re, sys, urllib.error, urllib.parse, urllib.request
from pathlib import PurePosixPath
from html import escape

API = "https://api.github.com"
READY = "foundation-autodev:ready"
FAILURES = {"failure", "timed_out", "action_required"}
# Repeated failed observations without a new commit must not loop forever.
MAX_SAME_HEAD_FAILED_OBSERVATIONS = 2

def ready_labeled(item: dict) -> bool:
    """Only a live, explicitly ready-labeled PR can consume commit CI reads."""
    labels = item.get("labels", [])
    return isinstance(labels, list) and any(
        (row.get("name") if isinstance(row, dict) else row) == READY
        for row in labels
    )

def request(url: str, token: str):
    if not url.startswith(API + "/"):
        raise ValueError("refusing non-GitHub API URL")
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "foundation-autodev-planner",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("GitHub response exceeds size limit")
            return json.loads(raw)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError("GitHub read failed: " + type(exc).__name__) from exc

def pages(url: str, token: str):
    result = []
    for page in range(1, 6):
        sep = "&" if "?" in url else "?"
        data = request(url + sep + urllib.parse.urlencode({"per_page":100,"page":page}), token)
        if not isinstance(data, list):
            raise ValueError("unexpected GitHub collection response")
        result.extend(data)
        if len(data) < 100:
            break
        if page == 5:
            raise ValueError("GitHub collection exceeds bounded 500-item read window")
    return result

def _metadata_document(body: str):
    """Extract one balanced JSON object from the trusted metadata comment."""
    text = body or ""
    marker = re.compile(r"<!--\s*foundation-autodev:\s*")
    matches = list(marker.finditer(text))
    if not matches:
        return None, None, text
    if len(matches) != 1:
        raise ValueError("metadata block must occur exactly once")
    start = matches[0].end()
    depth = 0
    in_string = escaped = False
    end = None
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                raise ValueError("metadata JSON is malformed")
            if depth == 0:
                end = index + 1
                break
    if end is None or not text[end:].lstrip().startswith("-->"):
        raise ValueError("metadata JSON is incomplete")
    raw = text[start:end]
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate metadata object key")
            result[key] = value
        return result
    closing = end + len(text[end:]) - len(text[end:].lstrip())
    outside = text[:matches[0].start()] + text[closing + 3:]
    return json.loads(raw, object_pairs_hook=unique_object), raw, outside


def metadata(body: str, issue_number: int):
    obj, _raw, _outside = _metadata_document(body)
    if obj is None:
        return [], []
    if not isinstance(obj, dict) or set(obj) - {"paths","depends_on","native_handoff"}:
        raise ValueError("unsupported metadata")
    paths, deps = obj.get("paths",[]), obj.get("depends_on",[])
    if not isinstance(paths,list) or len(paths)>20 or not isinstance(deps,list) or len(deps)>20:
        raise ValueError("metadata list exceeds limits")
    clean=[]
    for path in paths:
        if not safe_manifest_path(path):
            raise ValueError("unsafe repository path")
        clean.append(path)
    if any(type(x) is not int or x<1 or x==issue_number for x in deps):
        raise ValueError("invalid dependency")
    return sorted(set(clean)), sorted(set(deps))


def safe_manifest_path(value):
    """Validate a repository-relative path without traversal or control bytes."""
    return (isinstance(value, str) and 0 < len(value) <= 512
            and not any(ord(char) < 32 or ord(char) == 127 for char in value)
            and not value.startswith(("/", "~")) and "\\" not in value
            and all(part not in ("", ".", "..") and part.casefold() != ".git"
                    for part in value.split("/"))
            and str(PurePosixPath(value)) == value)


def native_handoff_candidate(body: str, issue_number: int):
    """Validate a machine-readable handoff proposal; never grant execution."""
    obj, _raw, outside = _metadata_document(body)
    if obj is None:
        return None
    handoff = obj.get("native_handoff") if isinstance(obj, dict) else None
    if handoff is None:
        return None
    if not isinstance(handoff, dict) or set(handoff) != {"anchor", "target", "calls", "acceptance_paths"}:
        raise ValueError("native handoff metadata must contain anchor, target, calls, acceptance_paths")
    anchor, target = handoff["anchor"], handoff["target"]
    if (not isinstance(anchor, str) or not 8 <= len(anchor) <= 256
            or not anchor.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in anchor)
            or anchor not in outside):
        raise ValueError("native handoff anchor must match exact issue text")
    if not safe_manifest_path(target):
        raise ValueError("native handoff target path is unsafe")
    calls = handoff["calls"]
    if not isinstance(calls, list) or not 2 <= len(calls) <= 3:
        raise ValueError("native handoff calls are invalid")
    # Match the current M1 reviewed-host operation vocabulary and order.
    # Construction is optional, but creation and prompt dispatch are mandatory.
    allowed = {"client.construct", "client.createSession", "session.startTurn"}
    operations = [call[0] if isinstance(call, list) and call else None for call in calls]
    expected = ["client.createSession", "session.startTurn"]
    if operations not in (expected, ["client.construct", *expected]):
        raise ValueError("native handoff call sequence is not reviewed")
    seen_ops, seen_effects, normalized_calls = set(), set(), []
    for call in calls:
        if not isinstance(call, list) or len(call) != 2:
            raise ValueError("native handoff call tuple is invalid")
        operation, effects = call
        if operation not in allowed or operation in seen_ops:
            raise ValueError("native handoff operation is not reviewed")
        if (not isinstance(effects, list) or not 1 <= len(effects) <= 8
                or any(not isinstance(x, str) or not x.strip() or len(x) > 64
                       or any(ord(char) < 32 or ord(char) == 127 for char in x)
                       for x in effects)
                or len(set(effects)) != len(effects)
                or seen_effects.intersection(effects)):
            raise ValueError("native handoff effects are invalid")
        seen_ops.add(operation)
        seen_effects.update(effects)
        normalized_calls.append([operation, effects])
    acceptance = handoff["acceptance_paths"]
    if (not isinstance(acceptance, list) or not 1 <= len(acceptance) <= 8
            or any(not safe_manifest_path(path) for path in acceptance)
            or len(set(acceptance)) != len(acceptance)
            or target in acceptance
            or any(not (path.startswith("tests/") and path.endswith(".py")
                        or path.startswith("deploy/") and path.endswith(".test.mjs"))
                   for path in acceptance)):
        raise ValueError("native handoff acceptance paths are invalid")
    return {
        "issue_number": issue_number, "anchor": anchor, "target": target,
        "calls": normalized_calls, "acceptance_paths": acceptance,
        "status": "CANDIDATE_ONLY_NOT_AUTHORIZED",
        "execution_authorized": False,
    }

def workflow_runs(base: str, token: str):
    """Read a bounded, paginated window of workflow runs for CI signal planning."""
    result = []
    for page in range(1, 6):
        payload = request(
            f"{base}/actions/runs?" + urllib.parse.urlencode({"per_page": 100, "page": page}),
            token,
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
            raise ValueError("unexpected GitHub workflow-runs response")
        batch = payload["workflow_runs"]
        result.extend(batch)
        if len(batch) < 100:
            break
        if page == 5:
            raise ValueError("GitHub workflow history exceeds bounded 500-run read window")
    return result


def workflow_runs_for_prs(base: str, token: str, prs: list[dict]):
    """Read CI results for current open PR heads, independent of repository history size."""
    result = []
    seen_shas = set()
    for pr in prs:
        if pr.get("state") != "open" or not ready_labeled(pr):
            continue
        if not isinstance(pr.get("head"), dict):
            raise ValueError("ready PR has no current head")
        sha = pr["head"].get("sha")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("open pull request has an invalid head SHA")
        if sha in seen_shas:
            continue
        seen_shas.add(sha)

        checks_payload = request(
            f"{base}/commits/{sha}/check-runs?per_page=100", token
        )
        if (not isinstance(checks_payload, dict)
                or not isinstance(checks_payload.get("check_runs"), list)
                or type(checks_payload.get("total_count")) is not int):
            raise ValueError("unexpected commit check-runs response")
        check_runs = checks_payload["check_runs"]
        if checks_payload["total_count"] > len(check_runs):
            raise ValueError("commit check-runs exceed bounded 100-item read window")
        for check in check_runs:
            if not isinstance(check, dict) or not isinstance(check.get("name"), str):
                raise ValueError("malformed commit check-run")
            result.append({
                "id": check.get("id", 0),
                "workflow_id": "check:" + check["name"],
                "name": check["name"],
                "head_sha": sha,
                "status": check.get("status"),
                "conclusion": check.get("conclusion"),
                "updated_at": check.get("completed_at") or check.get("started_at") or check.get("created_at") or "",
                "html_url": check.get("html_url") or check.get("details_url") or "",
            })

        status_payload = request(
            f"{base}/commits/{sha}/status?per_page=100", token
        )
        if (not isinstance(status_payload, dict)
                or not isinstance(status_payload.get("statuses"), list)):
            raise ValueError("unexpected commit statuses response")
        statuses = status_payload["statuses"]
        if len(statuses) >= 100:
            raise ValueError("commit statuses may exceed bounded 100-item read window")
        for status in statuses:
            if not isinstance(status, dict) or not isinstance(status.get("context"), str):
                raise ValueError("malformed commit status")
            state = status.get("state")
            conclusion = {
                "success": "success",
                "failure": "failure",
                "error": "failure",
            }.get(state)
            result.append({
                "id": status.get("id", 0),
                "workflow_id": "status:" + status["context"],
                "name": status["context"],
                "head_sha": sha,
                "status": "completed" if conclusion else "in_progress",
                "conclusion": conclusion,
                "updated_at": status.get("updated_at") or status.get("created_at") or "",
                "html_url": status.get("target_url") or status.get("url") or "",
            })
    return result


def conflict(a,b):
    if not a or not b: return True
    return any(x==y or x.startswith(y+"/") or y.startswith(x+"/") for x in a for y in b)

def build_plan(repo, issues, prs, runs, max_parallel=3):
    bynum={x["number"]:x for x in issues if "pull_request" not in x and type(x.get("number")) is int}
    ready=[]; observed=[]; blocked=[]; failures=[]
    for n, issue in sorted(bynum.items()):
        if issue.get("state")!="open": continue
        labels={x.get("name") if isinstance(x,dict) else x for x in issue.get("labels",[])}
        try:
            paths,deps=metadata(issue.get("body",""),n)
            handoff=native_handoff_candidate(issue.get("body",""),n)
            errors=[]
            if handoff is not None and paths != [handoff["target"]]:
                errors.append("native handoff target must be the sole declared task path")
            if handoff is not None and deps:
                errors.append("native handoff candidates must not declare dependencies")
        except (ValueError,TypeError,json.JSONDecodeError) as e:
            paths,deps,handoff=[],[],None
            errors=[str(e)]
        for dep in deps:
            if dep not in bynum or bynum[dep].get("state")!="closed": errors.append(f"dependency #{dep} not closed")
        item={"id":f"issue:{n}","kind":"issue","number":n,"title":issue.get("title",""),"url":issue.get("html_url",""),"paths":paths,"depends_on":deps,"blockers":errors}
        if handoff is not None:
            item["native_handoff"] = handoff
        if READY not in labels: observed.append(item)
        elif errors: blocked.append(item)
        else: ready.append(item)
    for pr in prs:
        if pr.get("state")!="open" or not isinstance(pr.get("head"),dict): continue
        sha=pr["head"].get("sha")
        matching=[r for r in runs if r.get("head_sha")==sha]
        latest={}
        for run in matching:
            key=run.get("workflow_id",run.get("name","unknown"))
            if key not in latest or (run.get("updated_at",""),run.get("id",0))>(latest[key].get("updated_at",""),latest[key].get("id",0)): latest[key]=run
        failed=[r for r in latest.values() if r.get("status")=="completed" and r.get("conclusion") in FAILURES]
        labels={x.get("name") if isinstance(x,dict) else x for x in pr.get("labels",[])}
        if failed and ready_labeled(pr):
            for run in failed:
                identity = run.get("workflow_id", run.get("name", "unknown"))
                observed_failures = {
                    (historical.get("id"), historical.get("updated_at", ""))
                    for historical in matching
                    if historical.get("workflow_id", historical.get("name", "unknown")) == identity
                    and historical.get("status") == "completed"
                    and historical.get("conclusion") in FAILURES
                }
                item = {"id": f"ci:{pr['number']}:{run.get('id')}",
                        "kind": "ci_failure", "number": pr["number"],
                        "title": f"CI failure: {pr.get('title','')}",
                        "url": run.get("html_url", ""), "paths": [],
                        "depends_on": [],
                        "head_sha": sha,
                        "failed_observations_same_head": len(observed_failures)}
                if len(observed_failures) > MAX_SAME_HEAD_FAILED_OBSERVATIONS:
                    item["blockers"] = ["REPEATED_CI_FAILURE_SAME_HEAD_NEEDS_HUMAN"]
                    blocked.append(item)
                else:
                    item["blockers"] = ["inspect failing job paths before parallel execution"]
                    failures.append(item)
    ready.extend(failures)
    ready.sort(key=lambda x:(x["number"],x["id"]))
    batches=[]; remaining=ready[:]
    while remaining:
        batch=[]; rest=[]
        for item in remaining:
            if len(batch)<max_parallel and all(not conflict(item["paths"],x["paths"]) for x in batch): batch.append(item)
            else: rest.append(item)
        if not batch: batch,rest=remaining[:1],remaining[1:]
        batches.append([x["id"] for x in batch]); remaining=rest
    handoffs = [
        {"id": item["id"], "number": item["number"], "url": item["url"],
         **item["native_handoff"]}
        for item in ready if item.get("native_handoff") is not None
    ]
    return {"repository":repo,"eligible_items":ready,"observed_items":observed,"blocked_items":blocked,"ci_failures":failures,"parallel_batches":batches,"native_handoff_candidates":handoffs,"max_parallel":max_parallel}


def native_handoff_manifest(repo, plan):
    """Emit only the exact untrusted candidate contract consumed by M1."""
    candidates = plan.get("native_handoff_candidates", [])
    if not isinstance(candidates, list) or len(candidates) > 100:
        raise ValueError("native handoff candidate manifest exceeds 100 entries")
    fields = {
        "issue_number", "anchor", "target", "calls", "acceptance_paths",
        "status", "execution_authorized",
    }
    normalized = []
    seen_issues = set()
    for item in candidates:
        if (type(item) is not dict
                or set(item) != fields | {"id", "number", "url"}
                or type(item.get("number")) is not int
                or type(item.get("issue_number")) is not int
                or item.get("issue_number") != item.get("number")
                or item.get("id") != f"issue:{item.get('number')}"
                or type(item.get("url")) is not str
                or item["url"] != f"https://github.com/{repo}/issues/{item.get('number')}"
                or type(item.get("anchor")) is not str
                or not 8 <= len(item["anchor"]) <= 256
                or item["anchor"] != item["anchor"].strip()
                or any(ord(char) < 32 or ord(char) == 127 for char in item["anchor"])
                or not safe_manifest_path(item.get("target"))
                or type(item.get("calls")) is not list
                or type(item.get("acceptance_paths")) is not list
                or item.get("status") != "CANDIDATE_ONLY_NOT_AUTHORIZED"
                or item.get("execution_authorized") is not False):
            raise ValueError("native handoff candidate shape or authority is invalid")
        number = item["issue_number"]
        if number in seen_issues:
            raise ValueError("duplicate native handoff issue candidate")
        seen_issues.add(number)
        operations = [call[0] if type(call) is list and call else None
                      for call in item["calls"]]
        if operations not in (
                ["client.createSession", "session.startTurn"],
                ["client.construct", "client.createSession", "session.startTurn"]):
            raise ValueError("native handoff candidate call sequence is invalid")
        seen_operations, seen_effects = set(), set()
        for call in item["calls"]:
            if type(call) is not list or len(call) != 2:
                raise ValueError("native handoff candidate call is invalid")
            operation, effects = call
            if (operation in seen_operations or type(effects) is not list
                    or not 1 <= len(effects) <= 8
                    or any(type(effect) is not str or not effect.strip()
                           or len(effect) > 64
                           or any(ord(char) < 32 or ord(char) == 127 for char in effect)
                           for effect in effects)
                    or len(set(effects)) != len(effects)
                    or seen_effects.intersection(effects)):
                raise ValueError("native handoff candidate effects are invalid")
            seen_operations.add(operation)
            seen_effects.update(effects)
        acceptance = item["acceptance_paths"]
        if (not 1 <= len(acceptance) <= 8
                or any(not safe_manifest_path(path) for path in acceptance)
                or len(set(acceptance)) != len(acceptance)
                or item["target"] in acceptance
                or any(not (
                    path.startswith("tests/") and path.endswith(".py")
                    or path.startswith("deploy/") and path.endswith(".test.mjs")
                ) for path in acceptance)):
            raise ValueError("native handoff candidate acceptance paths are invalid")
        normalized.append({key: item[key] for key in (
            "issue_number", "anchor", "target", "calls", "acceptance_paths",
            "status", "execution_authorized",
        )})
    return {
        "schema": "foundation-native-handoff-candidates/v1",
        "repository": repo,
        "native_handoff_candidates": normalized,
    }


def render_summary(plan):
    """Render bounded, source-safe identifiers only; never echo untrusted issue text."""
    lines = [
        "## Foundation auto-development plan",
        "Mode: read-only; no task execution, repository writes, approvals or merges.",
        (
            f"Eligible: {len(plan['eligible_items'])}; "
            f"blocked: {len(plan['blocked_items'])}; "
            f"observed: {len(plan['observed_items'])}; "
            f"CI failures: {len(plan['ci_failures'])}; "
        f"Native handoff candidates: {len(plan.get('native_handoff_candidates', []))}"
        ),
        "",
        "### Eligible parallel batches",
    ]
    for index, batch in enumerate(plan["parallel_batches"][:20], 1):
        lines.append(f"- Batch {index}: " + ", ".join(f"`{item_id}`" for item_id in batch[:8]))
    if len(plan["parallel_batches"]) > 20:
        lines.append(f"- … {len(plan['parallel_batches']) - 20} additional batches omitted")
    if not plan["parallel_batches"]:
        lines.append("- None")
    if plan.get("native_handoff_candidates"):
        lines.extend(["", "### Native handoff candidates (not authorized)"])
        for candidate in plan["native_handoff_candidates"][:20]:
            target = escape(candidate["target"])
            calls = "; ".join(
                f"<code>{escape(operation)}</code> effects="
                + ", ".join(f"<code>{escape(effect)}</code>" for effect in effects)
                for operation, effects in candidate["calls"]
            )
            acceptance = ", ".join(
                f"<code>{escape(path)}</code>" for path in candidate["acceptance_paths"]
            )
            lines.append(
                f"- `issue:{candidate['number']}` target=<code>{target}</code>; "
                f"calls: {calls}; independent acceptance: {acceptance}; "
                "execution_authorized=false"
            )
    if plan["blocked_items"]:
        lines.extend(["", "### Blocked"])
        for item in plan["blocked_items"][:20]:
            reasons = "; ".join(item["blockers"][:3]) or "blocked"
            lines.append(f"- `{item['id']}`: {reasons}")
        if len(plan["blocked_items"]) > 20:
            lines.append(f"- … {len(plan['blocked_items']) - 20} additional blocked items omitted")
    return "\n".join(lines) + "\n"


def current_issues(base: str, token: str):
    """Read active Issue work without fetching unbounded closed history.

    Resolve only dependency identities actually mentioned in active Issue
    metadata; an unknown or unavailable dependency stays blocked by build_plan.
    """
    # GitHub repositories may have >500 unrelated operational/diagnostic Issues.
    # Only exact opt-in ready work is eligible; never truncate a broad Issue feed.
    # Closed dependency IDs are still individually verified below.
    issues = pages(base + "/issues?state=open&labels=" + urllib.parse.quote(READY, safe=""), token)
    known = {item["number"] for item in issues
             if type(item) is dict and type(item.get("number")) is int}
    missing = set()
    for item in issues:
        if type(item) is not dict or "pull_request" in item:
            continue
        # Only opted-in work needs dependency resolution. Historical/unready
        # open Issues must not exhaust the bounded dependency read budget.
        labels = {label.get("name") if isinstance(label, dict) else label
                  for label in item.get("labels", [])}
        if READY not in labels:
            continue
        try:
            _, dependencies = metadata(item.get("body", ""), item.get("number"))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        missing.update(dependency for dependency in dependencies if dependency not in known)
    # Preserve the existing finite read contract instead of walking all history.
    if len(missing) > 100:
        raise ValueError("active Issue dependency set exceeds bounded 100-item window")
    for number in sorted(missing):
        try:
            dependency = request(f"{base}/issues/{number}", token)
        except RuntimeError:
            # No GET proof => dependency must remain blocked, not assumed closed.
            continue
        if (type(dependency) is dict and type(dependency.get("number")) is int
                and dependency["number"] == number
                and dependency.get("state") == "closed"
                and "pull_request" not in dependency):
            issues.append(dependency)
    return issues


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--repo",required=True); p.add_argument("--output",required=True); p.add_argument("--candidate-output"); p.add_argument("--summary")
    p.add_argument("--max-parallel",type=int,default=3); a=p.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",a.repo): p.error("repo must be owner/name")
    if not 1<=a.max_parallel<=8: p.error("max-parallel must be 1..8")
    token=os.environ.get("GITHUB_TOKEN")
    if not token: raise SystemExit("GITHUB_TOKEN is required")
    base=f"{API}/repos/{a.repo}"
    issues=current_issues(base,token)
    prs=pages(base+"/pulls?state=open",token)
    runs=workflow_runs_for_prs(base,token,prs)
    plan=build_plan(a.repo,issues,prs,runs,a.max_parallel)
    with open(a.output,"w",encoding="utf-8") as f: json.dump(plan,f,ensure_ascii=False,indent=2)
    if a.candidate_output:
        manifest=native_handoff_manifest(a.repo,plan)
        with open(a.candidate_output,"w",encoding="utf-8") as f:
            json.dump(manifest,f,ensure_ascii=False,indent=2)
    if a.summary:
        with open(a.summary,"a",encoding="utf-8") as f:
            f.write(render_summary(plan))
    print(json.dumps({
        "eligible": len(plan["eligible_items"]),
        "blocked": len(plan["blocked_items"]),
        "batches": len(plan["parallel_batches"]),
        "native_handoff_candidates": len(plan.get("native_handoff_candidates", [])),
    }))
if __name__=="__main__": main()
