from ai_foundation.evaluation import DeterministicEvaluator, EvalCase, SemanticEvaluator

def test_deterministic_eval_links_evidence_and_isolates_failure():
    def boom(): raise RuntimeError('x')
    results=DeterministicEvaluator().run((
        EvalCase('verified',lambda: True,('effect:1','readback:1')),
        EvalCase('bad',lambda: False,('effect:2',)),
        EvalCase('error',boom),
    ))
    assert [r.passed for r in results]==[True,False,False]
    assert results[0].evidence==('effect:1','readback:1')
    assert results[2].detail=='RuntimeError'

def test_semantic_eval_is_explicit_and_boolean_only():
    assert SemanticEvaluator(lambda payload: payload=='good').run('quality','good',('ev',)).passed
    try:
        SemanticEvaluator(lambda payload:'maybe').run('quality','x')
        assert False
    except TypeError: pass
