from ai_foundation.evaluation import EvalResult, summarize_gate

def test_gate_summary_is_deterministic_and_evidence_linked():
    s=summarize_gate((EvalResult('security',True,('sec:1',)),EvalResult('recovery',False,('rec:1','sec:1'))))
    assert not s.passed and s.total==2 and s.failed==('recovery',)
    assert s.evidence==('sec:1','rec:1')
