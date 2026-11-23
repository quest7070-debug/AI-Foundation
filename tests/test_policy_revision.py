from pathlib import Path
from ai_foundation.cedar import CedarPolicyBoundary
from ai_foundation.core import TaskPlan,Decision
ROOT=Path(__file__).parents[1]; C=ROOT/'.tools/cedar/cedar-policy-cli-aarch64-apple-darwin/cedar'
def test_policy_drift_after_boundary_creation_fails_closed(tmp_path):
 policy=tmp_path/'p.cedar'; policy.write_text((ROOT/'policy/default.cedar').read_text())
 b=CedarPolicyBoundary(C,policy,ROOT/'policy/schema.cedarschema',ROOT/'policy/entities.json')
 p=TaskPlan('r','write','x',canon_revision='c',policy_revision=b.revision,provenance='host:test')
 assert b.authorize(p) is Decision.ALLOW
 policy.write_text('forbid(principal, action, resource);')
 assert b.authorize(p) is Decision.DENY
def test_stale_bound_policy_revision_denied():
 b=CedarPolicyBoundary(C,ROOT/'policy/default.cedar',ROOT/'policy/schema.cedarschema',ROOT/'policy/entities.json')
 p=TaskPlan('r','write','x',policy_revision='stale')
 assert b.authorize(p) is Decision.DENY
