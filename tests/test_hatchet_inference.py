from ai_foundation.hatchet_inference import task_defaults
def test_hatchet_inference_disables_runtime_retry():
 x=task_defaults(); assert x is not None and x.retries==0
