from ai_foundation.task_result import TaskResult
def test_task_result_roundtrip_and_legacy():
 x=TaskResult('answer','VERIFIED','LOCAL',('e1',),'local:x');assert TaskResult.decode(x.encode())==x
 assert TaskResult.decode('old answer').output=='old answer'
