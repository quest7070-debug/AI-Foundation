"""New public Strata CODE acceptance: original source must fail until fixed."""

from ai_foundation.provider_catalog import detect, spec


def test_nonstring_provider_inputs_are_unknown_not_exceptions():
    for value in (1, True, ["GROQ"], {"name": "GROQ"}):
        assert spec(value) is None
    for value in (None, 1, True, ["not-a-key"], {"key": "not-a-key"}):
        assert detect(value) is None


def test_string_provider_identity_and_key_detection_are_preserved():
    assert spec("GROQ").name == "GROQ"
    assert spec("groq").name == "GROQ"
    assert spec("missing-provider") is None
    assert detect("gsk_" + "A" * 20) == "GROQ"
    assert detect("not-a-key") is None
