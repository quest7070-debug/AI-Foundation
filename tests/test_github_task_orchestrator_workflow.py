from pathlib import Path


def test_github_task_orchestrator_workflow_keeps_planning_read_only_without_artifacts():
    workflow = Path(".github/workflows/github-task-orchestrator.yml").read_text(
        encoding="utf-8"
    )
    assert "GITHUB_STEP_SUMMARY" in workflow
    assert "actions/upload-artifact" not in workflow.lower()
    assert "contents: write" not in workflow
    assert "issues: write" not in workflow
    assert "pull-requests: write" not in workflow
    assert "--summary" in workflow
    assert "pull_request_target:" in workflow
