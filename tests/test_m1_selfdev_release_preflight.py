"""Safety/identity contract for the owner-only, read-only release preflight."""
from pathlib import Path

from scripts import m1_selfdev_release_preflight as probe


SHA = "a" * 40


def event(sha=SHA, *, number=1419, branch=probe.PR_BRANCH):
    return {"action": "synchronize",
            "pull_request": {
                "number": number,
                "user": {"login": probe.OWNER},
                "head": {
                    "repo": {"full_name": probe.REPO},
                    "ref": branch,
                    "sha": sha}}}


ENV = {"GITHUB_EVENT_NAME": "pull_request",
       "GITHUB_REPOSITORY": probe.REPO}


def test_owner_head_scope_never_uses_loose_pr_or_wrong_revision():
    assert probe.scoped_event(event(), env=ENV, current_sha=SHA)
    for mismatch in (
        (event(number=1422), ENV, SHA),
        (event(branch="other"), ENV, SHA),
        (event(sha="b" * 40), ENV, SHA),
        (event(), {"GITHUB_EVENT_NAME": "workflow_dispatch",
                   "GITHUB_REPOSITORY": probe.REPO}, SHA),
    ):
        assert not probe.scoped_event(mismatch[0], env=mismatch[1],
                                      current_sha=mismatch[2])


def test_mobile_followup_exact_owner_and_applied_predecessor_only():
    approved_base={"ref":probe.PR_BRANCH,"sha":probe.FOLLOWUP_BASE_SHA}
    event_fixed=event(number=probe.FOLLOWUP_PR_NUMBER,
                      branch=probe.FOLLOWUP_BRANCH)
    event_fixed["pull_request"]["base"]=approved_base
    assert probe.scoped_event(event_fixed,env=ENV,current_sha=SHA)
    for changed in (
        {"number":probe.PR_NUMBER},
        {"base":{"ref":"main","sha":probe.FOLLOWUP_BASE_SHA}},
        {"base":{"ref":probe.PR_BRANCH,"sha":"f"*40}},
        {"head":{"ref":"other","sha":SHA,
                 "repo":{"full_name":probe.REPO}}},
    ):
        bad=dict(event_fixed)
        bad["pull_request"]={**event_fixed["pull_request"],**changed}
        assert not probe.scoped_event(bad,env=ENV,current_sha=SHA)


def test_mobile_terminal_replacement_source_stage_requires_exact_frozen_parent():
    candidate = event(number=probe.MOBILE_PR_NUMBER, branch=probe.MOBILE_BRANCH)
    candidate["pull_request"]["base"] = {
        "ref": probe.FOLLOWUP_BRANCH, "sha": probe.MOBILE_BASE_SHA}
    assert probe.scoped_event(candidate, env=ENV, current_sha=SHA)
    for overrides in (
        {"number": probe.FOLLOWUP_PR_NUMBER},
        {"base": {"ref": "main", "sha": probe.MOBILE_BASE_SHA}},
        {"base": {"ref": probe.FOLLOWUP_BRANCH, "sha": "b" * 40}},
        {"head": {"ref": probe.PR_BRANCH,
                  "sha": SHA, "repo": {"full_name": probe.REPO}}},
    ):
        changed = dict(candidate)
        changed["pull_request"] = {**candidate["pull_request"], **overrides}
        assert not probe.scoped_event(changed, env=ENV, current_sha=SHA)



def test_post_cutover_exact_owner_parent_and_source_staging_only():
    candidate = event(number=probe.POST_CUTOVER_PR_NUMBER,
                      branch=probe.POST_CUTOVER_BRANCH)
    candidate["pull_request"]["base"] = {
        "ref": probe.CODE_CAPACITY_BRANCH, "sha": probe.POST_CUTOVER_BASE_SHA}
    assert probe.scoped_event(candidate, env=ENV, current_sha=SHA)
    for changed in (
        {"number": probe.CODE_CAPACITY_PR_NUMBER},
        {"base": {"ref": probe.CODE_CAPACITY_BRANCH, "sha": "f"*40}},
        {"base": {"ref": "main", "sha": probe.POST_CUTOVER_BASE_SHA}},
        {"head": {"ref": probe.CODE_CAPACITY_BRANCH, "sha": SHA,
                  "repo": {"full_name": probe.REPO}}},
        {"user": {"login": "untrusted-other-user"}},
    ):
        case = dict(candidate)
        case["pull_request"] = {**candidate["pull_request"], **changed}
        assert not probe.scoped_event(case, env=ENV, current_sha=SHA)
    assert not probe.scoped_event(candidate, env=ENV, current_sha="f"*40)
    for path in ("scripts/m1_owner_production_recovery.py",
                 "scripts/m1_selfdev_release_preflight.py"):
        assert path in probe.SOURCE_FILES


def test_p0_operator_followup_source_stage_exact_prior_gateway_and_owner_only():
    candidate = event(number=probe.P0_OPERATOR_PR_NUMBER,
                      branch=probe.P0_OPERATOR_BRANCH)
    candidate["pull_request"]["base"] = {
        "ref": probe.POST_CUTOVER_BRANCH, "sha": probe.P0_OPERATOR_BASE_SHA}
    assert probe.scoped_event(candidate, env=ENV, current_sha=SHA)
    for changes in (
        {"number": probe.POST_CUTOVER_PR_NUMBER},
        {"base": {"ref": "main", "sha": probe.P0_OPERATOR_BASE_SHA}},
        {"base": {"ref": probe.POST_CUTOVER_BRANCH, "sha": "f"*40}},
        {"head": {"ref": probe.POST_CUTOVER_BRANCH, "sha": SHA,
                  "repo": {"full_name": probe.REPO}}},
        {"user": {"login": "untrusted"}},
    ):
        row = dict(candidate)
        row["pull_request"] = {**candidate["pull_request"], **changes}
        assert not probe.scoped_event(row, env=ENV, current_sha=SHA)
    assert not probe.scoped_event(candidate, env=ENV, current_sha="b"*40)
    for file in ("scripts/m1_owner_production_recovery.py",
                 "src/ai_foundation/operator_mcp_tools.py",
                 "tests/test_foundation_mcp_stdio.py"):
        assert file in probe.SOURCE_FILES


def test_code_capacity_exact_g8_successor_is_readonly_eligible_only():
    candidate = event(
        number=probe.CODE_CAPACITY_PR_NUMBER, branch=probe.CODE_CAPACITY_BRANCH)
    candidate["pull_request"]["base"] = {
        "ref": probe.MOBILE_BRANCH, "sha": probe.CODE_CAPACITY_BASE_SHA}
    assert probe.scoped_event(candidate, env=ENV, current_sha=SHA)
    for changed in (
        {"number": probe.MOBILE_PR_NUMBER},
        {"base": {"ref": "main", "sha": probe.CODE_CAPACITY_BASE_SHA}},
        {"base": {"ref": probe.MOBILE_BRANCH, "sha": "f" * 40}},
        {"head": {"ref": probe.MOBILE_BRANCH, "sha": SHA,
                  "repo": {"full_name": probe.REPO}}},
        {"user": {"login": "untrusted-other-user"}},
    ):
        case = dict(candidate)
        case["pull_request"] = {**candidate["pull_request"], **changed}
        assert not probe.scoped_event(case, env=ENV, current_sha=SHA)
    assert not probe.scoped_event(candidate, env=ENV, current_sha="f" * 40)
    for path in (
        "scripts/m1_development_ticket_factory.py",
        "scripts/m1_direct_development.py",
        "scripts/m1_strata_owner_ticket_admission.py",
        "scripts/m1_reviewed_strata_ticket.py",
        "scripts/m1_strata_ticket_overview.py",
    ):
        assert path in probe.SOURCE_FILES


def test_owner_preflight_only_reads_and_classifies_difference(tmp_path):
    candidate, owner = tmp_path / "pr", tmp_path / "owner"
    for root in (candidate, owner):
        for relative in probe.SOURCE_FILES:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("SAFE = True\n")
    # Changed owner checkout is not an installed-runtime proof.
    (owner / probe.SOURCE_FILES[0]).write_text("SAFE = False\n")
    calls = []
    def trusted(path):
        calls.append(str(path))
        return Path(path).read_bytes()
    def tunnel(**kwargs):
        calls.append("READONLY_TUNNEL_PROBE")
        return {"reason": "OWNER_SOURCE_INSTALL_REQUIRED"}
    observed = probe.inspect(
        event=event(), env=ENV, current_sha=SHA,
        system="Darwin", machine="arm64", uid=501, euid=501,
        candidate=candidate, owner_checkout=owner,
        trusted_bytes=trusted, tunnel_readiness=tunnel)
    assert observed["status"] == "READONLY_SOURCE_OBSERVED"
    assert observed["owner_checkout_different_modules"] == 1
    assert observed["owner_checkout_source_match"] is False
    assert observed["existing_tunnel_reason"] == "OWNER_SOURCE_INSTALL_REQUIRED"
    assert observed["model_calls"] == 0
    assert observed["service_mutations"] == 0
    assert observed["production_installed"] is False
    assert observed["remote_mcp_cycle_verified"] is False
    assert calls.count("READONLY_TUNNEL_PROBE") == 1
    assert len(calls) == len(probe.SOURCE_FILES) * 2 + 1


def test_owner_preflight_refuses_untrusted_head_or_machine_before_touching_paths():
    def forbidden(*args, **kwargs):
        raise AssertionError("NO_FILES_OR_MODEL_ALLOWED")
    defaults = dict(event=event(), env=ENV, current_sha=SHA,
                    system="Darwin", machine="arm64", uid=501, euid=501,
                    candidate="/not/read", owner_checkout="/not/read",
                    trusted_bytes=forbidden, tunnel_readiness=forbidden)
    assert probe.inspect(**{**defaults, "event": event(number=999)})["status"] == "BLOCKED"
    assert probe.inspect(**{**defaults, "uid": 502})["status"] == "BLOCKED"
    assert probe.inspect(**{**defaults, "system": "Linux"})["status"] == "BLOCKED"


def test_owner_preflight_never_exposes_source_exceptions(tmp_path):
    def untrusted(_):
        raise PermissionError("PRIVATE_OWNER_SECRET")
    result = probe.inspect(
        event=event(), env=ENV, current_sha=SHA,
        system="Darwin", machine="arm64", uid=501, euid=501,
        candidate=tmp_path, owner_checkout=tmp_path,
        trusted_bytes=untrusted, tunnel_readiness=lambda **_: {})
    assert result["status"] == "BLOCKED"
    assert "PRIVATE_OWNER_SECRET" not in str(result)
    assert result["model_calls"] == result["service_mutations"] == 0


def test_review_source_successor_exact_owner_parent_and_no_effect():
    candidate = event(number=probe.OWNER_REVIEW_PR_NUMBER,
                      branch=probe.OWNER_REVIEW_BRANCH)
    candidate["pull_request"]["base"] = {
        "ref": probe.P0_OPERATOR_BRANCH,
        "sha": probe.OWNER_REVIEW_BASE_SHA}
    assert probe.scoped_event(candidate, env=ENV, current_sha=SHA)
    for changed in (
        {"number": probe.P0_OPERATOR_PR_NUMBER},
        {"base": {"ref": "main", "sha": probe.OWNER_REVIEW_BASE_SHA}},
        {"base": {"ref": probe.P0_OPERATOR_BRANCH, "sha": "f"*40}},
        {"head": {"ref": probe.P0_OPERATOR_BRANCH,
                  "sha": SHA, "repo": {"full_name": probe.REPO}}},
        {"user": {"login": "untrusted"}},
    ):
        row = dict(candidate)
        row["pull_request"] = {**candidate["pull_request"], **changed}
        assert not probe.scoped_event(row, env=ENV, current_sha=SHA)
    assert not probe.scoped_event(candidate, env=ENV, current_sha="b"*40)
    for name in (
        "scripts/m1_operator_release_cli.py",
        "scripts/m1_development_review_candidate.py",
        "scripts/m1_development_owner_review.py",
        "src/ai_foundation/development_review_renderer.py",
        "tests/test_m1_development_owner_review.py",
        "tests/test_m1_operator_release_cli.py",
    ):
        assert name in probe.SOURCE_FILES


def test_runtime_import_successor_exact_owner_parent_and_no_effect():
    candidate = event(number=probe.RUNTIME_IMPORT_PR_NUMBER,
                      branch=probe.RUNTIME_IMPORT_BRANCH)
    candidate["pull_request"]["base"] = {
        "ref":probe.OWNER_REVIEW_BRANCH,
        "sha":probe.RUNTIME_IMPORT_BASE_SHA}
    assert probe.scoped_event(candidate,env=ENV,current_sha=SHA)
    for changed in (
        {"number":probe.OWNER_REVIEW_PR_NUMBER},
        {"base":{"ref":"main","sha":probe.RUNTIME_IMPORT_BASE_SHA}},
        {"base":{"ref":probe.OWNER_REVIEW_BRANCH,"sha":"b"*40}},
        {"head":{"ref":probe.OWNER_REVIEW_BRANCH,"sha":SHA,
                 "repo":{"full_name":probe.REPO}}},
        {"user":{"login":"untrusted"}},
    ):
        row=dict(candidate)
        row["pull_request"]={**candidate["pull_request"],**changed}
        assert not probe.scoped_event(row,env=ENV,current_sha=SHA)
    assert not probe.scoped_event(candidate,env=ENV,current_sha="b"*40)
    assert "scripts/operator_server.py" in probe.SOURCE_FILES
    assert "tests/test_operator_server_installed_import_root.py" in probe.SOURCE_FILES


def test_whole_selfdev_source_stage_only_for_exact_owner_frozen_parent():
    request = event(number=probe.SELFDEV_WHOLE_PR_NUMBER,
                    branch=probe.SELFDEV_WHOLE_BRANCH)
    request["pull_request"]["base"] = {
        "ref": probe.RUNTIME_IMPORT_BRANCH, "sha": probe.SELFDEV_WHOLE_BASE_SHA}
    assert probe.scoped_event(request, env=ENV, current_sha=SHA)
    for invalid in (
        {"number": 1510},
        {"user": {"login": "untrusted"}},
        {"base": {"ref": "main", "sha": probe.SELFDEV_WHOLE_BASE_SHA}},
        {"base": {"ref": probe.RUNTIME_IMPORT_BRANCH, "sha": "b"*40}},
    ):
        changed = dict(request)
        changed["pull_request"] = {**request["pull_request"], **invalid}
        assert not probe.scoped_event(changed, env=ENV, current_sha=SHA)
    assert not probe.scoped_event(request, env=ENV, current_sha="b"*40)
    for relative in ("src/ai_foundation/development_requests.py",
                     "src/ai_foundation/mcp_host.py",
                     "scripts/m1_development_ticket_factory.py",
                     "tests/test_development_requests.py"):
        assert relative in probe.SOURCE_FILES


def test_exact_m1_stage_has_no_duplicate_or_missing_replacement_files():
    assert len(probe.SOURCE_FILES) == len(set(probe.SOURCE_FILES))
    for relative in (
        "src/ai_foundation/development_host.py",
        "tests/test_mcp_direct_local_development.py",
        "src/ai_foundation/notification_boundary.py",
        "tests/test_notification_boundary.py",
        "src/ai_foundation/human_renderer.py",
        "tests/test_human_renderer.py",
        "tests/test_mcp_owner_grants.py",
        "scripts/m1_owner_grant_host_canary.py",
        "scripts/m1_owner_grant_stdio_e2e.py",
        "tests/test_operator_reconcile_restart_http.py",
        "scripts/m1_guarded_tunnel_refresh.py",
        "scripts/remote_gateway.py",
        "tests/test_remote_gateway.py",
        "tests/test_operator_server.py",
        "src/ai_foundation/operator_server.py",
        "scripts/operator_server.py",
        "tests/test_operator_development_state.py",
        "src/ai_foundation/klm_status.py",
        "tests/test_klm_status.py",
        "src/ai_foundation/preflight.py",
        "src/ai_foundation/operator.py",
        "tests/test_preflight.py",
    ):
        assert relative in probe.SOURCE_FILES


