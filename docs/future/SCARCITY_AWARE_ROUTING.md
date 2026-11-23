# Future concept: scarcity-aware capability routing

Status: FUTURE CONCEPT ONLY — not a current requirement, implementation claim, or verification-matrix PASS condition.

## Motivation
A provider may be broadly usable for CHAT while also being one of very few providers capable of a scarce function such as SEARCH. Consuming that provider's limited free quota on abundant work can make the scarce function unavailable later. Current example motivating the concept: Groq can participate in CHAT while also carrying scarce SEARCH capability.

## Concept
Routing may dynamically preserve providers that own scarce capabilities instead of using one fixed provider order for every capability.

For a requested capability, candidate ordering could consider:
- capability compatibility;
- current health;
- known quota/rate-limit state;
- scarcity of the candidate's other capabilities (how many viable alternatives exist for those capabilities);
- ordinary configured priority;
- local-model fallback policy.

A provider with a scarce capability remains eligible for ordinary work, but receives a preservation penalty there when adequate alternatives exist. Example: if SEARCH has only Groq while CHAT has several cloud providers plus Local LLMs, Groq can move toward the end of CHAT candidates (potentially immediately before Local fallback) while remaining high priority for SEARCH.

This must be dynamic rather than hardcoded to Groq. Adding Tavily, Exa, another search-capable provider, or changing provider/model capabilities should automatically change scarcity and therefore reservation pressure.

## Future design questions
- Define the scarcity/reservation score without creating unstable route oscillation.
- Decide how unknown quota differs from known low quota.
- Decide whether Local LLMs participate in scarcity calculation or remain a separate fallback class.
- Preserve deterministic/explainable route decisions and expose the reason in route evidence.
- Ensure provider/model add/remove and capability changes invalidate/recompute the score.
- Verify that preservation never makes a required capability unreachable or bypasses authority/cost policy.
- Add tests for scarce-capability reservation, inventory changes, quota exhaustion, failover, restart and concurrent requests before production adoption.

Do not implement this merely to satisfy the current full-system audit. Promote it into canonical routing requirements only after an explicit future design decision.
