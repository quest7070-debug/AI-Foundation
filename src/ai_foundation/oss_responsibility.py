from dataclasses import dataclass

@dataclass(frozen=True)
class OSSResponsibility:
    component: str
    owns: tuple[str,...]
    foundation_keeps: tuple[str,...]
    production_status: str

RESPONSIBILITIES=(
 OSSResponsibility('Pydantic AI',('agent loop','model/tool schema','structured agent output','model fallback mechanism'),('capability route policy','provider health/quota','Guard authority','credential policy'),'BOUNDARY_ONLY'),
 OSSResponsibility('Hatchet',('scheduling','queues','redelivery/retries','worker distribution','runtime observability'),('verified-step state','effect idempotency','reconciliation','Guard authority'),'VERIFIED_NOT_BOOTSTRAPPED'),
 OSSResponsibility('ToolHive',('MCP workload containment','tool process lifecycle','network isolation','tool audit boundary'),('tool capability scope','Guard authority','independent effect verification'),'MCP_PRODUCTION_BOUNDARY'),
 OSSResponsibility('Cedar',('authorization policy evaluation',),('Canon','privacy','approval','budget','effect state','verification','Guard authority'),'PRODUCTION_BOUNDARY'),
)

def validate_responsibilities():
    by={x.component:x for x in RESPONSIBILITIES}
    assert set(by)=={'Pydantic AI','Hatchet','ToolHive','Cedar'}
    assert all('Guard authority' in x.foundation_keeps for x in RESPONSIBILITIES)
    return True
