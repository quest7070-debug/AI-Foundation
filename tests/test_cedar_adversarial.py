from pathlib import Path
from ai_foundation.cedar import CedarPolicyBoundary
from ai_foundation.core import TaskPlan,Decision
ROOT=Path(__file__).parents[1]; C=ROOT/'.tools/cedar/cedar-policy-cli-aarch64-apple-darwin/cedar'
def b(): return CedarPolicyBoundary(C,ROOT/'policy/default.cedar',ROOT/'policy/schema.cedarschema',ROOT/'policy/entities.json')
def test_cedar_target_quote_injection_fails_closed():
 assert b().authorize(TaskPlan('r','write','x" , Action::"write"',canon_revision='c')) is Decision.DENY
def test_cedar_newline_target_fails_closed():
 assert b().authorize(TaskPlan('r','write','x\nfoo',canon_revision='c')) is Decision.DENY
