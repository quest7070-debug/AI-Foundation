"""Human-surface authority policy. Browser UI is one responsive surface; Echo is intentionally constrained."""
from dataclasses import dataclass
@dataclass(frozen=True)
class SurfacePolicy:
 name:str; approvals:bool; human_input:bool; provider_admin:bool; routing_admin:bool; tasks:bool
POLICIES={
 'responsive':SurfacePolicy('responsive',True,True,True,True,True),
 'echo':SurfacePolicy('echo',False,False,False,False,False),
}
def policy(surface):
 try:return POLICIES[surface]
 except KeyError:raise ValueError('unknown surface')
