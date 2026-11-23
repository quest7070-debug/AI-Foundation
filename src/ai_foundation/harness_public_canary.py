"""Compile-time public-only Harness smoke-test review bindings.

These are NOT general data-classification or final-code-review models. They
authorize only one source-pinned public fixture, so the native Harness may
exercise an external CODE proposal without forwarding private Issue content
and without depending on a speculative 9B classification. All other tasks
remain local; production use needs the actual trusted local 9B reviewers.
"""
from __future__ import annotations

import ast
import hashlib

from .model_work_roles import (
    ModelWorkContract, ModelWorkRole,
)

PUBLIC_CANARY_ID = "foundation-harness:add-v1"
PUBLIC_CANARY_PROMPT = (
    "Public nonsecret smoke test. Return ONLY Python source for one function "
    "def add(x, y): return x + y. No imports, execution, secrets, "
    "filesystem access or Markdown."
)
PUBLIC_CANARY_SOURCE = "def add(x, y):\n    return x + y\n"


def reviewed_public_canary(text):
    """One trusted fixed public payload, never arbitrary Issue/agent text."""
    if type(text) is not str or text != PUBLIC_CANARY_PROMPT:
        return ModelWorkContract(ModelWorkRole.LOCAL_DEVELOPMENT)
    return ModelWorkContract(
        role=ModelWorkRole.FOUNDATION_DEVELOPMENT,
        data_class="PUBLIC_NONSECRET",
        public_source=PUBLIC_CANARY_ID,
        reviewed_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        host_public_reviewed=True,
        external_transfer_allowed=True,
        local_data_reviewed=True,
        local_data_verdict="PUBLIC_NONSECRET",
    )


_EXPECTED_TREE = ast.dump(
    ast.parse(PUBLIC_CANARY_SOURCE), include_attributes=False)


def independent_public_canary_review(prompt, source):
    """Only byte-exact public fixture may reach the host's Draft writer.

    AST equality alone would ignore hidden comments/private source bytes.
    Compile without running and verify a fixed syntax tree as a second check.
    This never waives fixed tests, Guard, local reviews for real tasks or a
    fresh Free account receipt.
    """
    if (prompt != PUBLIC_CANARY_PROMPT or type(source) is not str
            or source != PUBLIC_CANARY_SOURCE):
        # AST equality alone ignores comments and source formatting. A model
        # could hide private text in comments while retaining the same tree,
        # then leak that text through the downstream Draft PR publisher.
        # The fixture is byte-exact by design; reject every addition.
        return False
    try:
        tree = ast.parse(source)
        compile(source, "<public-canary-review>", "exec")
    except (SyntaxError, ValueError, TypeError):
        return False
    return ast.dump(tree, include_attributes=False) == _EXPECTED_TREE
