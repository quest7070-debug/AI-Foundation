from ai_foundation.sensitive_input_scan import contains_sensitive_value


def test_detects_unlabelled_structured_private_and_secret_values():
    values = (
        "contact test@example.com",
        "連絡は09012345678へ",
        "連絡 080-1234-5678",
        "+81 90 1234 5678",
        "AKIA" + "A" * 16,
        "ASIA" + "B" * 16,
        "ghp_" + "a" * 36,
        "github_pat_" + "A" * 22 + "_" + "b" * 30,
        "sk-proj-" + "a" * 40,
        "-----BEGIN PRIVATE KEY-----\\nsynthetic\\n",
        "eyJ" + "a" * 10 + ".eyJ" + "b" * 10 + "." + "c" * 10,
    )
    assert all(contains_sensitive_value(value) for value in values)


def test_does_not_reinterpret_ordinary_explanations_as_private():
    for value in ("assistant: personal files", "Explain what an API key is",
                  "9B", "A user's name can appear in context"):
        assert not contains_sensitive_value(value)
    assert contains_sensitive_value("Assistant mentioned test@example.com")


def test_unknown_and_oversized_data_fail_local_only():
    assert contains_sensitive_value(None)
    assert contains_sensitive_value("x" * 262145)


def test_github_fine_grained_token_boundary_is_not_a_prose_match():
    # Synthetic values only; do not include or print real credentials.
    assert contains_sensitive_value("github_pat_" + "A" * 30)
    assert not contains_sensitive_value("prefixgithub_pat_" + "A" * 30)
    assert not contains_sensitive_value("github_pat_" + "A" * 10)


def test_temporary_aws_access_key_identifier_boundaries():
    # Only synthetic key identifiers; no actual credential material.
    assert contains_sensitive_value("ASIA" + "A" * 16)
    assert contains_sensitive_value("token=ASIA" + "Z" * 16 + ";")
    assert not contains_sensitive_value("prefixASIA" + "A" * 16)
    assert not contains_sensitive_value("ASIA" + "A" * 15)
    assert not contains_sensitive_value("ASIA" + "A" * 16 + "suffix")


def test_dsa_private_key_header_is_sensitive():
    assert contains_sensitive_value("-----BEGIN DSA PRIVATE KEY-----\nsynthetic\n")
    assert not contains_sensitive_value("DSA private key formats are documented")


def test_pgp_private_key_block_header_is_sensitive():
    # Synthetic armored-key header only, no real key material.
    assert contains_sensitive_value("-----BEGIN PGP PRIVATE KEY BLOCK-----\nsynthetic\n")
    assert not contains_sensitive_value("PGP private key block formats are documented")

def test_gitlab_personal_access_token_boundary():
    # Synthetic token-like strings only; no actual credential material.
    assert contains_sensitive_value("glpat-" + "A" * 20)
    assert contains_sensitive_value("token=glpat-" + "B" * 24 + ";")
    assert not contains_sensitive_value("prefixglpat-" + "A" * 20)
    assert not contains_sensitive_value("glpat-" + "A" * 19)
    assert not contains_sensitive_value("prefix_glpat-" + "A" * 20)
    assert not contains_sensitive_value("GitLab personal access token format")


def test_gitlab_runner_authentication_token_boundary():
    # Synthetic examples only; do not include real runner credentials.
    assert contains_sensitive_value("glrt-" + "A" * 20)
    assert contains_sensitive_value("runner=glrt-" + "B" * 24 + ";")
    assert not contains_sensitive_value("glrt-" + "A" * 19)
    assert not contains_sensitive_value("prefix_glrt-" + "A" * 20)
    assert not contains_sensitive_value("GitLab runner authentication token")


def test_slack_style_api_token_boundaries():
    # Synthetic tokens only; no workspace identifiers or live secrets.
    for prefix in ("xoxb-", "xoxp-", "xoxa-", "xoxr-", "xoxs-"):
        assert contains_sensitive_value("token=" + prefix + "A" * 16 + ";")
        assert not contains_sensitive_value(prefix + "A" * 15)
        assert not contains_sensitive_value("prefix_" + prefix + "A" * 16)
        assert not contains_sensitive_value(prefix + "A" * 16 + "_suffix")
    assert not contains_sensitive_value("Slack xoxb token format explained")
