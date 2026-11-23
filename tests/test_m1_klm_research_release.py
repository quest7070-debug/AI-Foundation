"""No-effect validation of the fixed KLM LLMPerks release gate."""
import pytest

from scripts import m1_klm_research_release as release


def event(message="test(m1): apply pinned KLM research reader with rollback"):
    return {"repository": {"full_name": release.REPO},
            "ref": "refs/heads/feat/klm-llmperks-research-intake-minimal-20261110",
            "head_commit": {"message": message}}


def test_release_identity_and_explicit_event_only():
    assert release.OLD == "cd12f042b186898b2734427b6ccb0f621c76f410"
    assert release.NEW == "82b79daee075f371794fe9f1e29ce74280da8cab"
    assert release.validate_issue(event()) == 564
    assert release.WORKFLOW == "Foundation M1 KLM LLMPerks research reader release"
    assert release.BODY.startswith("<!-- foundation-klm-research-release: ")
    with pytest.raises(release.Denied, match="RELEASE_FIXED_PUSH_REQUIRED"):
        release.validate_issue(event("unapproved"))
    with pytest.raises(release.Denied, match="RELEASE_FIXED_PUSH_REQUIRED"):
        release.validate_issue({**event(), "ref": "refs/heads/main"})
    with pytest.raises(release.Denied, match="RELEASE_FIXED_PUSH_REQUIRED"):
        release.validate_issue({**event(), "repository": {"full_name": "someone/else"}})


def test_fixed_release_hashes_disallow_moving_source():
    assert release.OLD_ENTRY_BLOB == "a50df834e2f514b069fe7194e7f326d89ce09067"
    assert release.NEW_ENTRY_BLOB == "cb642dc679c8de3f719e5797aca7167a4dcbe131"
    assert release.NEW_HANDLER == release.OLD_HANDLER
    assert release.LABEL == "dev.quest7070.ai-foundation.klm-drive"
    assert release.MARKER.startswith("<!-- foundation-klm-llmperks-release-receipt:")
