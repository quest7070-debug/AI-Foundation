# Python source repair Issue contract

A GitHub Issue is eligible only while open and labeled `foundation-autodev:ready`. This is a repository workflow convention, not a GitHub standard approval feature. The worker rereads the label and exact body before execution; only adding a label without a supported contract does not authorize arbitrary actions.

Use exactly one block, substituting actual immutable pins:

```foundation-autodev-task
{"recipe":"python-fixed-test","base":"main","base_sha":"<40 lowercase hex commit>","target":"src/ai_foundation/example.py","test":"tests/test_example.py","test_sha256":"<64 lowercase hex test hash>","instruction":"Fix the demonstrated test failure; preserve other behavior."}
```

Scope: one existing source file in src/ai_foundation, one existing fixed pytest file. No Issue-selected shell command. Base checkout HEAD and test bytes must match the approved contract. Baseline test must fail, changed source must pass. Generated code runs in a test sandbox denying writes, outbound network and user HOME reads. Pytest infrastructure errors stop; only real failed tests feed the bounded model repair. Guard, existing host lease, local9B provider and Draft-only publication remain. Dependencies absent from the selected host interpreter can block tests; none are installed automatically.

No generic real9B repair task has yet been accepted under this new recipe. Prior unattended PR #251 proves the older HTTP recipe only. CI/error-to-contract generation remains separate and not automatically authorized.
