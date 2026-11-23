from ai_foundation.human_surface import policy

def test_surface_authority_is_centralized():
 r,e=policy('responsive'),policy('echo')
 assert r.approvals and r.human_input and r.provider_admin and r.routing_admin and r.tasks
 assert not any((e.approvals,e.human_input,e.provider_admin,e.routing_admin,e.tasks))
