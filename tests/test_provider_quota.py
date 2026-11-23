from ai_foundation.provider_quota import groq_quota,mistral_short_quota

def test_groq_uses_documented_token_and_request_windows():
 q=groq_quota({'x-ratelimit-limit-tokens':'200','x-ratelimit-remaining-tokens':'50','x-ratelimit-reset-tokens':'8s','x-ratelimit-limit-requests':'1000','x-ratelimit-remaining-requests':'800','x-ratelimit-reset-requests':'2h'})
 assert q[0].remaining==25 and q[0].reset=='8s'
 assert q[1].remaining==80 and q[1].reset=='2h'

def test_groq_missing_trustworthy_header_is_not_invented():
 assert groq_quota({'x-ratelimit-limit-tokens':'200'}) is None

def test_mistral_only_exposes_short_window_from_generic_headers():
 q=mistral_short_quota({'X-RateLimit-Limit':'20','X-RateLimit-Remaining':'5','X-RateLimit-Reset':'1s'})
 assert q.remaining==25 and q.source=='mistral-response-headers'
 assert mistral_short_quota({}) is None
