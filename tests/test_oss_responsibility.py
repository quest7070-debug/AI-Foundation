from ai_foundation.oss_responsibility import RESPONSIBILITIES,validate_responsibilities

def test_oss_responsibility_manifest_is_complete_and_guard_stays_authoritative():
 assert validate_responsibilities()
 by={x.component:x for x in RESPONSIBILITIES}
 assert 'scheduling' in by['Hatchet'].owns
 assert 'model fallback mechanism' in by['Pydantic AI'].owns
 assert 'MCP workload containment' in by['ToolHive'].owns
 assert 'authorization policy evaluation' in by['Cedar'].owns
 assert all('Guard authority' in x.foundation_keeps for x in RESPONSIBILITIES)

def test_manifest_does_not_falsely_claim_unfinished_production_wiring():
 by={x.component:x for x in RESPONSIBILITIES}
 assert by['Hatchet'].production_status=='VERIFIED_NOT_BOOTSTRAPPED'
 assert by['Pydantic AI'].production_status=='BOUNDARY_ONLY'
 assert by['ToolHive'].production_status=='MCP_PRODUCTION_BOUNDARY'
