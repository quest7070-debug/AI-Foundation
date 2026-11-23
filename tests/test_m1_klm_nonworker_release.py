"""Read-only contract tests for the one-time SHA-pinned KLM #555 gate fix."""
import pytest

from scripts import m1_klm_nonworker_release as release


def event(message="test(m1): apply pinned KLM non-worker parent release"):
    return {"repository": {"full_name": release.REPO},
            "ref": "refs/heads/ops/klm-nonworker-release-20261110",
            "head_commit": {"message": message}}


def test_exact_source_and_owner_issue_only():
    assert release.OLD == "82b79daee075f371794fe9f1e29ce74280da8cab"
    assert release.NEW == "398592a317afc18dad7b1e55c3458324bb15889c"
    assert release.OLD_ENTRY_BLOB == release.NEW_ENTRY_BLOB == "cb642dc679c8de3f719e5797aca7167a4dcbe131"
    assert release.OLD_HANDLER == release.NEW_HANDLER
    assert release.validate_issue(event()) == 587
    assert release.WORKFLOW == "Foundation M1 KLM nonworker parent admission release"
    assert release.BODY == ('<!-- foundation-klm-nonworker-release: {"version":1,'
        '"release":"398592a317afc18dad7b1e55c3458324bb15889c",'
        '"previous_release":"82b79daee075f371794fe9f1e29ce74280da8cab",'
        '"scope":"klm-only","intent":"2026-11-10-user-fast-implementation"} -->')
    assert release.MARKER.startswith("<!-- foundation-klm-nonworker-release-receipt:v1:")
    for bad in (
        event("unapproved"),
        {**event(), "ref": "refs/heads/main"},
        {**event(), "repository": {"full_name": "other/repo"}},
    ):
        with pytest.raises(release.Denied, match="RELEASE_FIXED_PUSH_REQUIRED"):
            release.validate_issue(bad)


def test_release_fingerprints_pin_new_nonworker_logic_and_preserve_other_modules():
    from pathlib import Path
    source = Path(release.__file__).read_text()
    assert '"src/ai_foundation/klm_drive_work.py", "4d53c54f620393af5357757c93420de722ed5d45"' in source
    assert '"src/ai_foundation/klm_llmperks_source.py", "c6fbcfcef2241ae0718e6c5b1655c2b8ecf5c73a"' in source
    assert release.LABEL == "dev.quest7070.ai-foundation.klm-drive"
    assert release.ENTRY == "scripts/klm_drive_host_tick.py"
