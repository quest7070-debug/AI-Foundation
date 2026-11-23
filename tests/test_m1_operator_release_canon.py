"""Model-free isolated proof of the owner Canon source snapshot.

Fixture-only git repositories; no GitHub network, live Guard, service or
owner credentials are touched.
"""
import subprocess
from pathlib import Path

import pytest

from scripts import m1_operator_release_canon as canon


def _run(repo, *args):
    cp = subprocess.run(
        ["/usr/bin/git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=10, check=True)
    return cp.stdout.strip()


@pytest.fixture
def source_repo(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    _run(root, "init", "-q")
    data = {
        "docs/SOURCE_RELATIONSHIP.md": (
            "# Source Relationship\nThe repository "
            "quest7070-dev/AI-Foundation is the canonical source of truth.\n"
            "When GitHub and Drive disagree, GitHub wins.\n"
        ),
        "docs/SYSTEM_ROLE_BOUNDARIES.md": (
            "Status: ACTIVE CANON\n"
            "Foundation owns Canon, Guard/Cedar, durable effects, policy, privacy.\n"
            "Existing Foundation host / Guard / Harness own admitted development scope.\n"
            "Kandev and Paseo are NOT required as the default development task owner.\n"
        ),
        "docs/BOUNDARIES.md": "Guard owns only Canon and approval.\n",
        "src/ai_foundation/guard.py": (
            'class GuardCore:\n  APPROVAL_ACTIONS = {"production_deploy"}\n'
        ),
        "src/ai_foundation/release_gate.py": (
            'class GuardReleaseGate:\n  RELEASE_ACTION = "production_deploy"\n'
        ),
        "policy/schema.cedarschema": (
            'action "production_deploy" appliesTo { principal: User, resource: Target };\n'
        ),
    }
    for name, value in data.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(value, encoding="utf-8")
    _run(root, "add", ".")
    _run(root, "-c", "user.email=ci@example.invalid",
         "-c", "user.name=fixture", "commit", "-qm", "source")
    return root, _run(root, "rev-parse", "HEAD")


def test_release_canon_is_policy_content_digest_not_git_sha(source_repo):
    root, main = source_repo
    got = canon.observe_release_canon(root, remote_main=main)
    assert got["status"] == "CANON_SOURCE_VERIFIED"
    assert got["canon_revision"].startswith("canon-source/v1:")
    assert got["canon_revision"] != "github-main:" + main
    assert len(got["canon_revision"].split(":")[1]) == 64
    assert got["source_count"] == len(canon.CANON_FILES)
    assert got["source_main"] == main
    assert got["guard_writes"] == got["service_mutations"] == 0


def test_release_canon_accepts_explicit_no_kandev_executor_owner_role(source_repo):
    # The current owner explicitly excludes Kandev, not merely marking it
    # optional. Release Canon must still demand Foundation/Guard/Harness and
    # the production_deploy policy, without resurrecting historic wording.
    root, _ = source_repo
    path = root / "docs/SYSTEM_ROLE_BOUNDARIES.md"
    path.write_text(
        "Status: ACTIVE CANON\n"
        "Foundation owns Canon, Guard/Cedar, durable effects, policy.\n"
        "Existing Foundation host / Guard / Harness own admitted development scope.\n"
        "Kandev and Paseo are not active AI-Foundation development executors in the current owner workflow.\n",
        encoding="utf-8",
    )
    _run(root, "add", ".")
    _run(root, "-c", "user.email=ci@example.invalid", "-c",
         "user.name=fixture", "commit", "-qm", "updated roles")
    sha = _run(root, "rev-parse", "HEAD")
    assert canon.observe_release_canon(root, remote_main=sha)["status"] == (
        "CANON_SOURCE_VERIFIED"
    )


def test_release_canon_reobserves_current_remote_not_cached_ref(
        source_repo, monkeypatch):
    root, main = source_repo
    observed = []
    monkeypatch.setattr(
        canon, "_live_main",
        lambda r: observed.append(str(r)) or main)
    got = canon.observe_release_canon(root)
    assert got["source_main"] == main
    assert observed == [str(root)]


def test_release_canon_rejects_missing_local_main(source_repo):
    root, _ = source_repo
    with pytest.raises(canon.CanonSourceDenied,
                       match="CANON_SOURCE_MAIN_NOT_ANCESTOR"):
        canon.observe_release_canon(root, remote_main="a" * 40)


def test_release_canon_refuses_fake_remote_revision(source_repo):
    root, _ = source_repo
    with pytest.raises(canon.CanonSourceDenied,
                       match="CANON_SOURCE_REMOTE_UNTRUSTED"):
        canon.observe_release_canon(root, remote_main="attested-by-model")


def test_release_canon_rejects_invalid_canon_declaration(source_repo):
    root, _ = source_repo
    path = root / "docs/SYSTEM_ROLE_BOUNDARIES.md"
    path.write_text("Status: SUPERSEDED\n", encoding="utf-8")
    _run(root, "add", ".")
    _run(root, "-c", "user.email=ci@example.invalid",
         "-c", "user.name=fixture", "commit", "-qm", "supersede")
    sha = _run(root, "rev-parse", "HEAD")
    with pytest.raises(canon.CanonSourceDenied,
                       match="CANON_SOURCE_DECLARATION_INVALID"):
        canon.observe_release_canon(root, remote_main=sha)


def test_release_canon_rejects_missing_release_policy(source_repo):
    root, _ = source_repo
    path = root / "src/ai_foundation/guard.py"
    path.write_text("class GuardCore: pass\n", encoding="utf-8")
    _run(root, "add", ".")
    _run(root, "-c", "user.email=ci@example.invalid",
         "-c", "user.name=fixture", "commit", "-qm", "remove-deploy")
    sha = _run(root, "rev-parse", "HEAD")
    with pytest.raises(canon.CanonSourceDenied,
                       match="CANON_SOURCE_RELEASE_POLICY_MISSING"):
        canon.observe_release_canon(root, remote_main=sha)


def test_release_canon_revision_changes_on_policy_change(source_repo):
    root, main = source_repo
    baseline = canon.observe_release_canon(root, remote_main=main)
    path = root / "docs/BOUNDARIES.md"
    path.write_text("Guard owns only Canon and approval.\nNew scope guard.\n")
    _run(root, "add", ".")
    _run(root, "-c", "user.email=ci@example.invalid",
         "-c", "user.name=fixture", "commit", "-qm", "modify-policy")
    sha = _run(root, "rev-parse", "HEAD")
    changed = canon.observe_release_canon(root, remote_main=sha)
    assert baseline["canon_revision"] != changed["canon_revision"]


def test_release_canon_ignores_unrelated_git_metadata(source_repo):
    root, main = source_repo
    baseline = canon.observe_release_canon(root, remote_main=main)
    _run(root, "-c", "user.email=ci@example.invalid",
         "-c", "user.name=fixture", "commit", "--allow-empty",
         "-qm", "metadata")
    sha = _run(root, "rev-parse", "HEAD")
    same = canon.observe_release_canon(root, remote_main=sha)
    assert baseline["canon_revision"] == same["canon_revision"]


def test_release_canon_rejects_missing_bounded_policy_blob(source_repo):
    root, _ = source_repo
    (root / "policy/schema.cedarschema").unlink()
    _run(root, "add", "-u")
    _run(root, "-c", "user.email=ci@example.invalid",
         "-c", "user.name=fixture", "commit", "-qm", "remove-policy")
    sha = _run(root, "rev-parse", "HEAD")
    with pytest.raises(canon.CanonSourceDenied,
                       match="CANON_SOURCE_FILE_UNAVAILABLE"):
        canon.observe_release_canon(root, remote_main=sha)


def test_release_canon_rejects_superseded_development_authority_sentence(source_repo):
    # GitHub main remains authoritative, but an old Kandev-only role
    # declaration is no longer accepted as the current Foundation policy.
    root, _ = source_repo
    path = root / "docs/SYSTEM_ROLE_BOUNDARIES.md"
    path.write_text("Status: ACTIVE CANON\n"
                    "Foundation owns semantic and product-specific control.\n",
                    encoding="utf-8")
    _run(root, "add", ".")
    _run(root, "-c", "user.email=ci@example.invalid",
         "-c", "user.name=fixture", "commit", "-qm", "old-roles")
    sha = _run(root, "rev-parse", "HEAD")
    with pytest.raises(canon.CanonSourceDenied,
                       match="CANON_SOURCE_DECLARATION_INVALID"):
        canon.observe_release_canon(root, remote_main=sha)


def test_installed_canon_uses_verified_local_predecessor_without_network(
        source_repo, monkeypatch):
    from scripts import m1_development_ticket_factory as tickets
    from scripts import m1_development_review_candidate as review
    root, initial = source_repo
    monkeypatch.setattr(tickets, "_owner_local_repo", lambda: root)
    monkeypatch.setattr(review, "_installed_live_source_repo", lambda owner: root)
    monkeypatch.setattr(canon, "_live_main", lambda *_: pytest.fail(
        "remote lookup is not local execution authority"))
    expected = canon.observe_release_canon(root, remote_main=initial)
    installed = canon.observe_installed_canon(root)
    assert installed["canon_revision"] == expected["canon_revision"]
    assert installed["source_main"] == initial
    assert installed["authority_kind"] == "VERIFIED_M1_INSTALLED_SOURCE_SNAPSHOT"
    assert installed["guard_writes"] == installed["service_mutations"] == 0
    def unverified(_):
        raise ValueError("OWNER_INSTALLED_REVIEW_SOURCE_UNVERIFIED")
    monkeypatch.setattr(review, "_installed_live_source_repo", unverified)
    with pytest.raises(ValueError, match="OWNER_INSTALLED_REVIEW_SOURCE_UNVERIFIED"):
        canon.observe_installed_canon(root)
