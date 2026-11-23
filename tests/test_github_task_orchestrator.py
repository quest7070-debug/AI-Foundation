import json
from pathlib import Path
from scripts.github_task_orchestrator import build_plan, metadata, conflict, render_summary

def issue(n,state="open",labels=None,body=""):
    return {"number":n,"state":state,"labels":labels or [],"body":body,"title":f"Task {n}"}

def test_unlabeled_work_is_observed_not_executable():
    plan=build_plan("x/y",[issue(1)],[],[])
    assert len(plan["observed_items"])==1 and not plan["eligible_items"]

def test_dependency_must_be_closed():
    body='<!-- foundation-autodev: {"paths":["src/a.py"],"depends_on":[2]} -->'
    plan=build_plan("x/y",[issue(1,labels=["foundation-autodev:ready"],body=body),issue(2)],[],[])
    assert len(plan["blocked_items"])==1

def test_path_conflict_serializes_and_unknown_scope_is_exclusive():
    assert conflict(["src/a"],["src/a/test.py"])
    assert conflict([],["src/b"])
    assert not conflict(["src/a.py"],["src/b.py"])

def test_bad_metadata_blocks_opted_in_issue():
    body='<!-- foundation-autodev: {"paths":["../secret"]} -->'
    plan=build_plan("x/y",[issue(1,labels=["foundation-autodev:ready"],body=body)],[],[])
    assert plan["blocked_items"] and not plan["eligible_items"]

def test_latest_success_suppresses_old_failure():
    pr={"number":4,"state":"open","head":{"sha":"abc"},"labels":["foundation-autodev:ready"]}
    runs=[{"id":1,"workflow_id":2,"head_sha":"abc","status":"completed","conclusion":"failure","updated_at":"2026-01-01"},
          {"id":2,"workflow_id":2,"head_sha":"abc","status":"completed","conclusion":"success","updated_at":"2026-01-02"}]
    assert build_plan("x/y",[],[pr],runs)["ci_failures"]==[]

def test_pr_events_use_trusted_main_without_checking_out_pr_code():
    workflow_path = Path(__file__).resolve().parents[1] / ".github/workflows/github-task-orchestrator.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    assert "  pull_request_target:" in workflow
    assert "\n  pull_request:" not in workflow
    assert "persist-credentials: false" in workflow
    assert "ref: main" in workflow
    assert "pull_request.head.sha" not in workflow
    assert "contents: read" in workflow
    assert "issues: read" in workflow
    assert "pull-requests: read" in workflow
    assert "actions: read" in workflow


def test_render_summary_is_bounded_and_does_not_echo_untrusted_titles():
    plan = build_plan(
        "x/y",
        [issue(1, labels=["foundation-autodev:ready"], body='<!-- foundation-autodev: {"paths":["src/a.py"]} -->'),
         issue(2, labels=["foundation-autodev:ready"], body='<!-- foundation-autodev: {"paths":["src/a.py"]} -->')],
        [],
        [],
        max_parallel=1,
    )
    plan["eligible_items"][0]["title"] = "untrusted <script>alert(1)</script>"
    summary = render_summary(plan)
    assert "Batch 1" in summary
    assert "Mode: read-only" in summary
    assert "issue:1" in summary
    assert "untrusted" not in summary
    assert "script" not in summary


def native_handoff_body(*, anchor="Implement one bounded task", target="src/task.py",
                        operation="session.startTurn", acceptance=None, include_construct=False):
    import json
    calls = [["client.createSession", ["create-session"]],
             [operation, ["run-session"]]]
    if include_construct:
        calls.insert(0, ["client.construct", ["construct-client"]])
    metadata = {
        "paths": ["src/task.py"],
        "depends_on": [],
        "native_handoff": {
            "anchor": anchor,
            "target": target,
            "calls": calls,
            "acceptance_paths": acceptance or ["tests/test_task.py"],
        },
    }
    return anchor + "\n\n<!-- foundation-autodev: " + json.dumps(metadata) + " -->"


def test_reviewed_native_handoff_is_emitted_as_candidate_not_authority():
    body = native_handoff_body()
    plan = build_plan(
        "x/y",
        [issue(31, labels=["foundation-autodev:ready"], body=body)],
        [], [],
    )
    candidates = plan["native_handoff_candidates"]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["issue_number"] == 31
    assert candidate["target"] == "src/task.py"
    assert candidate["acceptance_paths"] == ["tests/test_task.py"]
    assert candidate["status"] == "CANDIDATE_ONLY_NOT_AUTHORIZED"
    assert candidate["execution_authorized"] is False
    summary = render_summary(plan)
    assert "client.createSession" in summary
    assert "create-session" in summary
    assert "tests/test_task.py" in summary
    assert "Implement one bounded task" not in summary


def test_native_handoff_rejects_unreviewed_calls_and_bad_anchor():
    bad_call = native_handoff_body(operation="session.startTurnShell")
    bad_anchor = native_handoff_body().replace("Implement one bounded task", "Different issue text", 1)
    for body in (bad_call, bad_anchor):
        plan = build_plan(
            "x/y", [issue(32, labels=["foundation-autodev:ready"], body=body)], [], []
        )
        assert not plan["native_handoff_candidates"]
        assert plan["blocked_items"]


def test_native_handoff_requires_fixed_independent_acceptance_paths():
    body = native_handoff_body(acceptance=["src/unrelated.py"])
    plan = build_plan(
        "x/y", [issue(33, labels=["foundation-autodev:ready"], body=body)], [], []
    )
    assert not plan["native_handoff_candidates"]
    assert plan["blocked_items"]


def test_native_handoff_accepts_reviewed_host_client_construction_call():
    body = native_handoff_body(include_construct=True)
    plan = build_plan(
        "x/y", [issue(34, labels=["foundation-autodev:ready"], body=body)], [], []
    )
    candidates = plan["native_handoff_candidates"]
    assert len(candidates) == 1
    assert [call[0] for call in candidates[0]["calls"]] == [
        "client.construct", "client.createSession", "session.startTurn"
    ]


def test_native_handoff_rejects_reordered_or_incomplete_native_call_sequence():
    import json
    body = native_handoff_body()
    metadata_start = body.index("<!-- foundation-autodev: ") + len("<!-- foundation-autodev: ")
    metadata_end = body.index(" -->", metadata_start)
    document = json.loads(body[metadata_start:metadata_end])
    calls = document["native_handoff"]["calls"]
    invalid_sequences = [
        [calls[1], calls[0]],
        [calls[0]],
        [["session.startTurn", ["run-session"]], ["client.createSession", ["create-session"]]],
    ]
    for invalid in invalid_sequences:
        document["native_handoff"]["calls"] = invalid
        candidate_body = body[:metadata_start] + json.dumps(document) + body[metadata_end:]
        plan = build_plan(
            "x/y",
            [issue(35, labels=["foundation-autodev:ready"], body=candidate_body)],
            [], [],
        )
        assert not plan["native_handoff_candidates"]
        assert plan["blocked_items"]


def test_native_handoff_requires_dependency_free_issue():
    import json
    body = native_handoff_body()
    marker = "<!-- foundation-autodev: "
    start = body.index(marker) + len(marker)
    end = body.index(" -->", start)
    metadata = json.loads(body[start:end])
    metadata["depends_on"] = [99]
    body = body[:start] + json.dumps(metadata) + body[end:]
    plan = build_plan(
        "x/y", [issue(54, labels=["foundation-autodev:ready"], body=body),
                issue(99, state="closed")], [], []
    )
    assert not plan["native_handoff_candidates"]
    assert plan["blocked_items"]


def test_native_handoff_target_must_match_the_planner_write_scope():
    body = native_handoff_body(target="src/different.py")
    plan = build_plan(
        "x/y", [issue(36, labels=["foundation-autodev:ready"], body=body)], [], []
    )
    assert not plan["native_handoff_candidates"]
    assert plan["blocked_items"]


def test_candidate_manifest_stays_transient_without_artifact_or_write_permissions():
    workflow_path = Path(__file__).resolve().parents[1] / ".github/workflows/github-task-orchestrator.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    assert "--candidate-output" in workflow
    assert "foundation-native-handoff-candidates.json" in workflow
    assert "actions/upload-artifact" not in workflow.lower()
    assert "actions: write" not in workflow
    assert "issues: write" not in workflow
    assert "contents: write" not in workflow


def test_native_handoff_manifest_is_compact_and_versioned():
    import pytest
    from scripts.github_task_orchestrator import native_handoff_manifest
    candidate = {
        "id": "issue:41", "number": 41, "issue_number": 41,
        "url": "https://github.com/quest7070-dev/AI-Foundation/issues/41",
        "anchor": "Implement one bounded task", "target": "src/task.py",
        "calls": [["client.createSession", ["create-session"]],
                  ["session.startTurn", ["run-session"]]],
        "acceptance_paths": ["tests/test_task.py"],
        "status": "CANDIDATE_ONLY_NOT_AUTHORIZED",
        "execution_authorized": False,
    }
    plan = {"native_handoff_candidates": [candidate]}
    manifest = native_handoff_manifest("quest7070-dev/AI-Foundation", plan)
    assert manifest == {
        "schema": "foundation-native-handoff-candidates/v1",
        "repository": "quest7070-dev/AI-Foundation",
        "native_handoff_candidates": [{
            key: candidate[key] for key in (
                "issue_number", "anchor", "target", "calls", "acceptance_paths",
                "status", "execution_authorized",
            )
        }],
    }
    import copy
    wrong_url = copy.deepcopy(candidate)
    wrong_url["url"] = "https://github.com/quest7070-dev/AI-Foundation/issues/99"
    with pytest.raises(ValueError, match="shape or authority"):
        native_handoff_manifest("quest7070-dev/AI-Foundation", {
            "native_handoff_candidates": [wrong_url],
        })
    malformed_candidates = []
    boolean_issue = copy.deepcopy(candidate)
    boolean_issue["issue_number"] = True
    malformed_candidates.append(boolean_issue)
    malformed_calls = copy.deepcopy(candidate)
    malformed_calls["calls"][1][1] = "run-session"
    malformed_candidates.append(malformed_calls)
    whitespace_anchor = copy.deepcopy(candidate)
    whitespace_anchor["anchor"] = "        "
    malformed_candidates.append(whitespace_anchor)
    unsafe_acceptance = copy.deepcopy(candidate)
    unsafe_acceptance["acceptance_paths"] = ["src/not-a-test.py"]
    malformed_candidates.append(unsafe_acceptance)
    for malformed in malformed_candidates:
        with pytest.raises(ValueError):
            native_handoff_manifest("quest7070-dev/AI-Foundation", {
                "native_handoff_candidates": [malformed],
            })
    duplicate = copy.deepcopy(candidate)
    with pytest.raises(ValueError, match="duplicate native handoff issue"):
        native_handoff_manifest("quest7070-dev/AI-Foundation", {
            "native_handoff_candidates": [candidate, duplicate],
        })
    with pytest.raises(ValueError, match="exceeds 100"):
        native_handoff_manifest(
            "quest7070-dev/AI-Foundation",
            {"native_handoff_candidates": [candidate] * 101},
        )


def test_metadata_rejects_duplicate_json_keys_instead_of_last_value_wins():
    duplicate_top_level = '<!-- foundation-autodev: {"paths":["src/a.py"],"paths":["src/b.py"]} -->'
    duplicate_nested = '<!-- foundation-autodev: {"paths":["src/a.py"],"native_handoff":{"anchor":"one bounded task","anchor":"other bounded task","target":"src/a.py","calls":[],"acceptance_paths":["tests/test_task.py"]}} -->'
    for body in (duplicate_top_level, duplicate_nested):
        plan = build_plan(
            "x/y", [issue(51, labels=["foundation-autodev:ready"], body=body)], [], []
        )
        assert not plan["eligible_items"]
        assert plan["blocked_items"]


def test_native_handoff_rejects_whitespace_only_anchor():
    body = native_handoff_body(anchor="        ")
    plan = build_plan(
        "x/y", [issue(52, labels=["foundation-autodev:ready"], body=body)], [], []
    )
    assert not plan["native_handoff_candidates"]
    assert plan["blocked_items"]


def test_native_handoff_anchor_must_exist_outside_metadata_comment():
    body = native_handoff_body()
    body = body.replace("Implement one bounded task\n\n", "", 1)
    plan = build_plan(
        "x/y", [issue(53, labels=["foundation-autodev:ready"], body=body)], [], []
    )
    assert not plan["native_handoff_candidates"]
    assert plan["blocked_items"]


def test_metadata_document_returns_anchor_text_outside_comment():
    from scripts.github_task_orchestrator import _metadata_document
    body = native_handoff_body(anchor="Keep this anchor outside metadata")
    document, raw, outside = _metadata_document(body)
    assert document["native_handoff"]["anchor"] == "Keep this anchor outside metadata"
    assert "Keep this anchor outside metadata" in outside
    assert raw not in outside


def test_metadata_document_without_comment_preserves_entire_issue_body():
    from scripts.github_task_orchestrator import _metadata_document
    body = "ordinary issue text without machine metadata"
    document, raw, outside = _metadata_document(body)
    assert document is None
    assert raw is None
    assert outside == body
    plan = build_plan("x/y", [issue(60, body=body)], [], [])
    assert len(plan["observed_items"]) == 1
    assert not plan["blocked_items"]



def test_workflow_runs_paginates_beyond_first_hundred(monkeypatch):
    from scripts import github_task_orchestrator as planner
    calls = []
    def fake_request(url, token):
        calls.append(url)
        page = int(url.rsplit("page=", 1)[1])
        if page == 1:
            return {"workflow_runs": [{"id": number} for number in range(100)]}
        if page == 2:
            return {"workflow_runs": [{"id": 100}, {"id": 101}]}
        raise AssertionError("pagination should stop after the short page")
    monkeypatch.setattr(planner, "request", fake_request)
    runs = planner.workflow_runs("https://api.github.com/repos/x/y", "token")
    assert len(runs) == 102
    assert [run["id"] for run in runs[-2:]] == [100, 101]
    assert len(calls) == 2


def test_workflow_runs_for_prs_queries_only_current_open_head_commits(monkeypatch):
    from scripts import github_task_orchestrator as planner
    sha = "a" * 40
    pr = {"number": 7, "state": "open", "head": {"sha": sha},
          "labels": ["foundation-autodev:ready"]}
    calls = []

    def fake_request(url, token):
        calls.append(url)
        if url.endswith("/check-runs?per_page=100"):
            return {"total_count": 2, "check_runs": [
                {"id": 10, "name": "unit", "status": "completed",
                 "conclusion": "failure", "completed_at": "2026-01-01",
                 "html_url": "https://example.test/unit"},
                {"id": 11, "name": "focused", "status": "completed",
                 "conclusion": "success", "completed_at": "2026-01-02",
                 "html_url": "https://example.test/focused"},
            ]}
        if url.endswith("/status?per_page=100"):
            return {"statuses": [
                {"id": 12, "context": "legacy", "state": "success",
                 "updated_at": "2026-01-03", "target_url": "https://example.test/legacy"}
            ]}
        raise AssertionError(url)

    monkeypatch.setattr(planner, "request", fake_request)
    runs = planner.workflow_runs_for_prs(
        "https://api.github.com/repos/x/y", "token", [pr, pr,
        {"number": 8, "state": "closed", "head": {"sha": "b" * 40}}],
    )
    assert len(runs) == 3
    assert {run["name"] for run in runs} == {"unit", "focused", "legacy"}
    assert len(calls) == 2
    assert all(sha in url for url in calls)


def test_workflow_runs_for_prs_fails_closed_on_truncated_check_runs(monkeypatch):
    import pytest
    from scripts import github_task_orchestrator as planner
    sha = "c" * 40
    monkeypatch.setattr(
        planner, "request",
        lambda url, _token: {"total_count": 101, "check_runs": [{}] * 100}
        if "/check-runs?" in url else {"statuses": []},
    )
    with pytest.raises(ValueError, match="exceed bounded"):
        planner.workflow_runs_for_prs(
            "https://api.github.com/repos/x/y", "token",
            [{"number": 9, "state": "open", "head": {"sha": sha},
              "labels": ["foundation-autodev:ready"]}],
        )


def test_workflow_runs_for_prs_latest_rerun_suppresses_old_failure(monkeypatch):
    from scripts import github_task_orchestrator as planner
    sha = "d" * 40
    pr = {"number": 10, "state": "open", "head": {"sha": sha},
          "labels": ["foundation-autodev:ready"]}
    monkeypatch.setattr(
        planner, "request",
        lambda url, _token: {
            "total_count": 2,
            "check_runs": [
                {"id": 1, "name": "unit", "status": "completed",
                 "conclusion": "failure", "completed_at": "2026-01-01"},
                {"id": 2, "name": "unit", "status": "completed",
                 "conclusion": "success", "completed_at": "2026-01-02"},
            ],
        } if "/check-runs?" in url else {"statuses": []},
    )
    runs = planner.workflow_runs_for_prs(
        "https://api.github.com/repos/x/y", "token", [pr]
    )
    assert build_plan("x/y", [], [pr], runs)["ci_failures"] == []


def test_workflow_runs_rejects_malformed_collection(monkeypatch):
    import pytest
    from scripts import github_task_orchestrator as planner
    monkeypatch.setattr(planner, "request", lambda _url, _token: {"runs": []})
    with pytest.raises(ValueError, match="workflow-runs response"):
        planner.workflow_runs("https://api.github.com/repos/x/y", "token")



def test_pages_rejects_silent_truncation_at_five_hundred(monkeypatch):
    import pytest
    from scripts import github_task_orchestrator as planner
    monkeypatch.setattr(planner, "request", lambda _url, _token: [{}] * 100)
    with pytest.raises(ValueError, match="bounded 500-item"):
        planner.pages("https://api.github.com/repos/x/y/issues", "token")


def test_workflow_runs_rejects_silent_truncation_at_five_hundred(monkeypatch):
    import pytest
    from scripts import github_task_orchestrator as planner
    monkeypatch.setattr(
        planner, "request", lambda _url, _token: {"workflow_runs": [{}] * 100}
    )
    with pytest.raises(ValueError, match="bounded 500-run"):
        planner.workflow_runs("https://api.github.com/repos/x/y", "token")


def test_current_issue_inventory_filters_ready_at_github_before_bounded_paging(monkeypatch):
    from scripts import github_task_orchestrator as planner
    body = '<!-- foundation-autodev: {"paths":["src/a.py"],"depends_on":[12]} -->'
    seen = []
    def fetch(url, _token):
        seen.append(url)
        if "/issues?state=open&labels=foundation-autodev%3Aready" in url:
            return [issue(11, labels=[planner.READY], body=body)]
        if url.endswith("/issues/12"):
            return issue(12, state="closed")
        raise AssertionError("unfiltered Issue inventory would exceed 500: " + url)
    monkeypatch.setattr(planner, "request", fetch)
    items = planner.current_issues("https://api.github.com/repos/x/y", "token")
    plan = planner.build_plan("x/y", items, [], [])
    assert [item["id"] for item in plan["eligible_items"]] == ["issue:11"]
    assert len(seen) == 2
    assert "labels=foundation-autodev%3Aready" in seen[0]


def test_current_issue_inventory_avoids_unbounded_closed_history(monkeypatch):
    from scripts import github_task_orchestrator as planner
    body = '<!-- foundation-autodev: {"paths":["src/task.py"],"depends_on":[2]} -->'
    requested = []
    def fetch(url, _token):
        requested.append(url)
        if "/issues?state=open" in url:
            return [issue(1, labels=["foundation-autodev:ready"], body=body), issue(3)]
        if url.endswith("/issues/2"):
            return issue(2, state="closed")
        raise AssertionError(url)
    monkeypatch.setattr(planner, "request", fetch)
    issues = planner.current_issues("https://api.github.com/repos/x/y", "token")
    plan = planner.build_plan("x/y", issues, [], [])
    assert [entry["id"] for entry in plan["eligible_items"]] == ["issue:1"]
    assert not plan["blocked_items"]
    assert all("state=all" not in url and "state=closed" not in url for url in requested)
    assert len(requested) == 2


def test_current_issue_inventory_fails_closed_on_missing_dependency(monkeypatch):
    from scripts import github_task_orchestrator as planner
    body = '<!-- foundation-autodev: {"paths":["src/task.py"],"depends_on":[8]} -->'
    def fetch(url, _token):
        if "/issues?state=open" in url:
            return [issue(1, labels=["foundation-autodev:ready"], body=body),
                    issue(2, labels=["foundation-autodev:ready"],
                          body='<!-- foundation-autodev: {"paths":["src/other.py"]} -->')]
        if url.endswith("/issues/8"):
            raise RuntimeError("GitHub read failed")
        raise AssertionError(url)
    monkeypatch.setattr(planner, "request", fetch)
    plan = planner.build_plan("x/y", planner.current_issues("https://api.github.com/repos/x/y", "token"), [], [])
    assert [item["id"] for item in plan["eligible_items"]] == ["issue:2"]
    assert plan["blocked_items"][0]["blockers"] == ["dependency #8 not closed"]



def test_current_issue_inventory_ignores_unready_dependency_fanout(monkeypatch):
    from scripts import github_task_orchestrator as planner
    calls = []
    def fetch(url, _token):
        calls.append(url)
        if "/issues?state=open" in url:
            rows = [
                issue(n, body='<!-- foundation-autodev: {"paths":["src/task.py"],"depends_on":[' + str(1000+n) + ']} -->')
                for n in range(1, 103)
            ] + [issue(200, labels=["foundation-autodev:ready"],
                       body='<!-- foundation-autodev: {"paths":["src/ready.py"],"depends_on":[300]} -->')]
            return rows[100:] if "page=2" in url else rows[:100]
        if url.endswith("/issues/300"):
            return issue(300, state="closed")
        raise AssertionError("unready Issue must not trigger dependency fetch: " + url)
    monkeypatch.setattr(planner, "request", fetch)
    items = planner.current_issues("https://api.github.com/repos/x/y", "token")
    plan = planner.build_plan("x/y", items, [], [])
    assert [entry["id"] for entry in plan["eligible_items"]] == ["issue:200"]
    assert len(calls) == 3
    assert calls[-1].endswith("/issues/300")


def test_ready_issue_metadata_rejects_unsafe_manifest_paths():
    """Ready Issue paths use the same strict policy as native handoff paths."""
    for path in (".git/config", "src/.GIT/config", "src/task\\u0000.py",
                 "src/task\\u007f.py", "src/" + "x" * 510):
        body = '<!-- foundation-autodev: ' + json.dumps({"paths": [path]}) + ' -->'
        plan = build_plan("x/y", [issue(99, labels=["foundation-autodev:ready"],
                                         body=body)], [], [])
        assert not plan["eligible_items"]
        assert plan["blocked_items"][0]["blockers"] == ["unsafe repository path"]
    valid = '<!-- foundation-autodev: {"paths":["src/task.py"]} -->'
    plan = build_plan("x/y", [issue(99, labels=["foundation-autodev:ready"],
                                     body=valid)], [], [])
    assert [item["id"] for item in plan["eligible_items"]] == ["issue:99"]


def test_native_handoff_rejects_control_characters_in_effect_names():
    """Effect labels are metadata, never a channel for control characters."""
    import json
    from scripts.github_task_orchestrator import native_handoff_manifest
    for bad in ("create\n-session", "create\t-session", "create\x7f-session"):
        body = native_handoff_body()
        marker = "<!-- foundation-autodev: "
        start = body.index(marker) + len(marker)
        end = body.index(" -->", start)
        document = json.loads(body[start:end])
        document["native_handoff"]["calls"][0][1] = [bad]
        body = body[:start] + json.dumps(document) + body[end:]
        plan = build_plan("x/y", [issue(73, labels=["foundation-autodev:ready"],
                                         body=body)], [], [])
        assert not plan["native_handoff_candidates"]
        assert plan["blocked_items"]

        valid = {
            "id": "issue:73", "number": 73, "issue_number": 73,
            "url": "https://github.com/x/y/issues/73",
            "anchor": "Implement one bounded task", "target": "src/task.py",
            "calls": [["client.createSession", [bad]],
                      ["session.startTurn", ["run-session"]]],
            "acceptance_paths": ["tests/test_task.py"],
            "status": "CANDIDATE_ONLY_NOT_AUTHORIZED",
            "execution_authorized": False,
        }
        import pytest
        with pytest.raises(ValueError, match="effects are invalid"):
            native_handoff_manifest("x/y", {"native_handoff_candidates": [valid]})


def test_unready_prs_cause_no_commit_check_requests(monkeypatch):
    from scripts import github_task_orchestrator as planner
    def no_network(*_):
        raise AssertionError("unready PR must not trigger commit status calls")
    monkeypatch.setattr(planner, "request", no_network)
    prs = [
        {"number": 100, "state": "open", "head": {"sha": "bad-sha"},
         "labels": []},
        {"number": 101, "state": "closed", "head": {"sha": "a" * 40},
         "labels": ["foundation-autodev:ready"]},
    ]
    assert planner.workflow_runs_for_prs(
        "https://api.github.com/repos/x/y", "token", prs) == []


def test_ready_pr_missing_exact_head_still_fails_closed(monkeypatch):
    import pytest
    from scripts import github_task_orchestrator as planner
    monkeypatch.setattr(planner, "request", lambda *_: None)
    with pytest.raises(ValueError, match="current head"):
        planner.workflow_runs_for_prs(
            "https://api.github.com/repos/x/y", "token",
            [{"number": 102, "state": "open", "head": None,
              "labels": [{"name": "foundation-autodev:ready"}]}],
        )


def test_pending_same_head_check_clears_stale_failure_signal():
    sha = "d" * 40
    pr = {"number": 103, "state": "open", "head": {"sha": sha},
          "labels": ["foundation-autodev:ready"]}
    runs = [
        {"id": 1, "workflow_id": "check:unit", "head_sha": sha,
         "status": "completed", "conclusion": "failure",
         "updated_at": "2026-11-10T10:00:00Z"},
        {"id": 2, "workflow_id": "check:unit", "head_sha": sha,
         "status": "in_progress", "conclusion": None,
         "updated_at": "2026-11-10T10:01:00Z"},
    ]
    assert build_plan("x/y", [], [pr], runs)["ci_failures"] == []



def test_repeated_failures_same_head_stop_but_new_commit_resets_feedback():
    sha = "f" * 40
    pr = {"number": 91, "state": "open", "head": {"sha": sha},
          "labels": ["foundation-autodev:ready"]}
    failures = [
        {"id": i, "workflow_id": "check:unit", "name": "unit",
         "head_sha": sha, "status": "completed", "conclusion": "failure",
         "updated_at": f"2026-11-05T00:0{i}:00Z"}
        for i in (1, 2, 3)
    ]
    first = build_plan("x/y", [], [pr], failures[:1])
    second = build_plan("x/y", [], [pr], failures[:2])
    assert len(first["ci_failures"]) == len(second["ci_failures"]) == 1
    assert second["ci_failures"][0]["failed_observations_same_head"] == 2
    stopped = build_plan("x/y", [], [pr], failures)
    assert stopped["ci_failures"] == []
    assert len(stopped["blocked_items"]) == 1
    assert stopped["blocked_items"][0]["blockers"] == [
        "REPEATED_CI_FAILURE_SAME_HEAD_NEEDS_HUMAN"
    ]
    assert stopped["parallel_batches"] == []
    assert stopped["native_handoff_candidates"] == []

    fresh_sha = "a" * 40
    fresh_pr = {**pr, "head": {"sha": fresh_sha}}
    new_failure = {**failures[0], "id": 50, "head_sha": fresh_sha}
    reset = build_plan("x/y", [], [fresh_pr], failures + [new_failure])
    assert len(reset["ci_failures"]) == 1
    assert reset["ci_failures"][0]["head_sha"] == fresh_sha
    assert reset["ci_failures"][0]["failed_observations_same_head"] == 1

    newer_success = {**failures[2], "id": 60, "conclusion": "success",
                     "updated_at": "2026-11-05T00:04:00Z"}
    recovered = build_plan("x/y", [], [pr], failures + [newer_success])
    assert recovered["ci_failures"] == []
    assert recovered["blocked_items"] == []


def test_new_queued_check_without_start_time_suppresses_stale_failure(monkeypatch):
    from scripts import github_task_orchestrator as planner
    sha = "b" * 40
    pr = {"number": 96, "state": "open", "head": {"sha": sha},
          "labels": ["foundation-autodev:ready"]}
    def request(url, _token):
        if "/check-runs?" in url:
            return {"total_count": 2, "check_runs": [
                {"id": 10, "name": "unit", "status": "completed",
                 "conclusion": "failure", "completed_at": "2026-11-05T00:01:00Z"},
                {"id": 11, "name": "unit", "status": "queued",
                 "conclusion": None, "started_at": None, "completed_at": None,
                 "created_at": "2026-11-05T00:02:00Z"},
            ]}
        return {"statuses": []}
    monkeypatch.setattr(planner, "request", request)
    observations = planner.workflow_runs_for_prs(
        "https://api.github.com/repos/x/y", "token", [pr])
    assert observations[1]["updated_at"] == "2026-11-05T00:02:00Z"
    plan = planner.build_plan("x/y", [], [pr], observations)
    assert plan["ci_failures"] == []
    assert plan["blocked_items"] == []


def test_m1_planner_uses_isolated_trusted_main_checkout():
    # The real M1 planner lost scripts/github_task_orchestrator.py when
    # another legacy workflow cleaned the shared default checkout.
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/github-task-orchestrator.yml").read_text()
    run_scoped = ".foundation-orchestrator/${{ github.run_id }}-${{ github.run_attempt }}"
    assert "runs-on: [self-hosted, macOS, ARM64]" in workflow
    assert "ref: main" in workflow  # PR-head and Issue source never execute.
    assert f"path: {run_scoped}" in workflow
    assert f"working-directory: {run_scoped}" in workflow
    assert '"$PWD" != "$FOUNDATION_ORCHESTRATOR_ROOT"' in workflow
    assert '! -f scripts/github_task_orchestrator.py' in workflow
    assert '"$(git rev-parse HEAD)" != "$(git rev-parse refs/remotes/origin/main)"' in workflow
    assert "ORCHESTRATOR_TRUSTED_MAIN_SOURCE_DRIFT" in workflow
    assert 'expected="$GITHUB_WORKSPACE/.foundation-orchestrator/${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"' in workflow
    assert "ORCHESTRATOR_CLEANUP_SCOPE_UNVERIFIED" in workflow
    assert 'rm -rf -- "$expected"' in workflow
    assert "if: always()" in workflow
    assert "persist-credentials: false" in workflow
