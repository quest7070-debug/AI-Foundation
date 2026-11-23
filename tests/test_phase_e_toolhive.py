import os
from pathlib import Path
import pytest
from ai_foundation.core import CanonContract, TaskPlan
from ai_foundation.evaluation import DeterministicEvaluator, EvalCase, summarize_gate
from ai_foundation.guard import GuardCore
from ai_foundation.instrumentation import ObservedGuard
from ai_foundation.observability import JsonlTraceSink, Tracer, read_jsonl_trace
from ai_foundation.run_report import build_run_report
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.toolhive import ToolHiveFilesystemPort

ROOT=Path(__file__).resolve().parents[1]; THV=ROOT/'.tools/toolhive/thv'; MOUNT=Path('/tmp/ai-foundation-toolhive')

@pytest.mark.skipif(os.getenv('AI_FOUNDATION_TOOLHIVE_E2E')!='1' or not THV.exists(),reason='live ToolHive E2E is opt-in')
def test_real_toolhive_effect_persists_trace_and_evidence_report(tmp_path):
    MOUNT.mkdir(parents=True,exist_ok=True); target=MOUNT/'phase-e-observed.txt'; target.unlink(missing_ok=True)
    store=SQLiteGuardStore(tmp_path/'guard.db'); trace=tmp_path/'trace.jsonl'
    port=ToolHiveFilesystemPort(THV,'ai-foundation-fs',MOUNT); plan=TaskPlan('phase-e-live','write',str(target),text='phase-e-live-value',canon_revision='c1',exclusive_target=True,effect_id='phase-e-live-effect')
    result=ObservedGuard(GuardCore(store.load(),100,store),Tracer(JsonlTraceSink(trace))).execute(plan,CanonContract('repo','c1'),port,'phase-e-live-value')
    events=read_jsonl_trace(trace)
    evals=DeterministicEvaluator().run((
        EvalCase('guard-verified',lambda:result=='VERIFIED_COMPLETE',('effect:phase-e-live-effect',)),
        EvalCase('real-readback',lambda:target.read_text()=='phase-e-live-value',('readback:'+str(target),)),
        EvalCase('durable-state',lambda:store.load().effects['phase-e-live-effect'].status.value=='VERIFIED',('store:effect:phase-e-live-effect',)),
        EvalCase('trace-safe',lambda:'phase-e-live-value' not in trace.read_text(),('trace:safe-metadata',)),
    ))
    report=build_run_report(events,evals)
    assert summarize_gate(evals).passed and report.passed and report.span_count==1
    assert 'effect:phase-e-live-effect' in report.evidence_ids
