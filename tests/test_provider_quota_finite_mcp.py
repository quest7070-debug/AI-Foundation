from ai_foundation.provider_quota import _pct, groq_quota, mistral_short_quota

def test_nonfinite_quota_inputs_are_unknown():
    for bad in ("nan", "NaN", "inf", "-inf", float("nan"), float("inf")):
        assert _pct(bad, 100) is None
        assert _pct(10, bad) is None

def test_finite_quota_behavior_is_preserved():
    assert _pct("25", "100") == 25.0
    assert _pct(-3, 100) == 0.0
    assert _pct(200, 100) == 100.0
    assert _pct(10, 0) is None
    assert _pct(None, 100) is None
    assert groq_quota({"x-ratelimit-remaining-tokens":"nan", "x-ratelimit-limit-tokens":"100",
                       "x-ratelimit-remaining-requests":"2", "x-ratelimit-limit-requests":"4"}) is None
    assert mistral_short_quota({"x-ratelimit-remaining":"1", "x-ratelimit-limit":"inf"}) is None
