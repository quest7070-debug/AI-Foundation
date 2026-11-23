"""Focused, no-model release contract for installed KLM 398592 -> #624."""
from types import SimpleNamespace

import pytest
from scripts import m1_klm_fairness_release as release


def event(message="test(m1): apply pinned KLM fairness release"):
    return {"repository": {"full_name": release.REPO},
            "ref": "refs/heads/ops/klm-fairness-pinned-release-20261111",
            "head_commit": {"message": message}}


def live_pr():
    return {"state": "open", "draft": True, "user": {"login": release.OWNER},
            "head": {"sha": release.NEW, "ref": release.DATA_BRANCH,
                     "repo": {"full_name": release.REPO}},
            "base": {"sha": release.OLD}}


def test_exact_pins_and_unrelated_modules_unchanged():
    assert release.OLD == "398592a317afc18dad7b1e55c3458324bb15889c"
    assert release.NEW == "799a1ad8a0584da6e2a852a363e5edfd61454bf8"
    assert release.OLD_ENTRY_BLOB == release.NEW_ENTRY_BLOB
    assert release.OLD_HANDLER == release.NEW_HANDLER
    assert release.PR == 624
    assert release.validate_issue(event()) == 624
    from pathlib import Path
    source = Path(release.__file__).read_text()
    assert '"src/ai_foundation/klm_drive_work.py", "0536eea6be8a6f4b5cb2c38870500890065bf4d6"' in source
    assert '"src/ai_foundation/klm_llmperks_source.py", "c6fbcfcef2241ae0718e6c5b1655c2b8ecf5c73a"' in source
    assert release.LABEL == "dev.quest7070.ai-foundation.klm-drive"


@pytest.mark.parametrize("bad", [
    event("not reviewed"),
    {**event(), "ref": "refs/heads/main"},
    {**event(), "repository": {"full_name": "wrong/repo"}},
])
def test_unreviewed_push_fails_closed(bad):
    with pytest.raises(release.Denied, match="RELEASE_FIXED_PUSH_REQUIRED"):
        release.validate_issue(bad)


def test_explicit_owner_pr_review_and_exact_sha_required(monkeypatch):
    observed = []
    def fetch(token):
        assert token == "fixture-token"
        observed.append("exact-get-624")
        return {**live_pr(), "body": "Approved\n" + release.APPROVAL + "\n"}
    monkeypatch.setattr(release, "exact_pr_readback", fetch)
    n, dest = release.checked_request(event(), "fixture-token")
    assert n == 624 and dest.endswith("/pulls/624")
    assert observed == ["exact-get-624"]


def test_missing_approval_or_data_drift_denied_before_effect(monkeypatch):
    rows=[{**live_pr(), "body": ""}]
    monkeypatch.setattr(release, "exact_pr_readback", lambda token: rows[0])
    with pytest.raises(release.Denied, match="EXACT_OWNER_RELEASE_REVIEW_REQUIRED"):
        release.checked_request(event(),"fixture-token")
    rows[0]={**live_pr(), "body": release.APPROVAL + "\n" + release.APPROVAL}
    with pytest.raises(release.Denied, match="EXACT_OWNER_RELEASE_REVIEW_REQUIRED"):
        release.checked_request(event(),"fixture-token")
    rows[0]={**live_pr(), "body": release.APPROVAL}
    rows[0]["head"]={**live_pr()["head"], "sha": "a"*40}
    with pytest.raises(release.Denied, match="RELEASE_DATA_PR_DRIFT_OR_UNTRUSTED"):
        release.checked_request(event(),"fixture-token")
    rows[0]={**live_pr(),"body":release.APPROVAL}
    assert release.checked_request(event(),"fixture-token")[0]==624


def test_exact_pr_get_is_single_narrow_url_and_bounded(monkeypatch):
    import json
    calls=[]
    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def read(self, amount):
            assert amount == 131073
            return json.dumps({"number":624}).encode()
    def fetch(request, timeout):
        calls.append((request.full_url,request.get_method(),timeout))
        return Response()
    monkeypatch.setattr(release.urllib.request, "urlopen", fetch)
    assert release.exact_pr_readback("fixture") == {"number":624}
    assert calls == [("https://api.github.com/repos/"
                      "quest7070-dev/AI-Foundation/pulls/624","GET",12)]


def test_exact_pr_readback_rejects_mismatched_issue(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self,*a): return None
        def read(self, amount): return b'{"number":625}'
    monkeypatch.setattr(release.urllib.request, "urlopen", lambda *a, **k: Response())
    with pytest.raises(release.Denied, match="RELEASE_PR_RESPONSE_IDENTITY_INVALID"):
        release.exact_pr_readback("fixture")
