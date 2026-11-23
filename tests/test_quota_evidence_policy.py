from ai_foundation.quota_evidence import *
def test_groq_documented_headers_are_two_window_authoritative():
 e=groq_header_evidence({'x-ratelimit-limit-tokens':'100','x-ratelimit-remaining-tokens':'80','x-ratelimit-reset-tokens':'7s','x-ratelimit-limit-requests':'1000','x-ratelimit-remaining-requests':'250','x-ratelimit-reset-requests':'1h'})
 assert (e.short_remaining,e.long_remaining)==(80,25) and free_registration_allowed(e)
def test_groq_missing_one_window_fails_closed():
 e=groq_header_evidence({'x-ratelimit-limit-tokens':'100','x-ratelimit-remaining-tokens':'80'}); assert not free_registration_allowed(e)
def test_groq_malformed_and_zero_limit_fail_closed():
 assert not free_registration_allowed(groq_header_evidence({'x-ratelimit-limit-tokens':'0','x-ratelimit-remaining-tokens':'0','x-ratelimit-limit-requests':'x','x-ratelimit-remaining-requests':'1'}))
def test_mistral_normal_key_header_is_not_enough_for_free_registration():
 e=mistral_header_evidence({'X-RateLimit-Limit':'100','X-RateLimit-Remaining':'50','X-RateLimit-Reset':'2s'}); assert e.short_remaining==50 and not free_registration_allowed(e)
