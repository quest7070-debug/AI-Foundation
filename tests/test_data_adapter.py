import json,pytest
from ai_foundation.capability_request import CapabilityRequest
from ai_foundation.data_adapter import build_data_specialist

def test_json_operation_is_host_bound():
 s=build_data_specialist(CapabilityRequest("DATA",data_operation="json_summary"))
 r=s.analyze('[1,2,3]')
 out=json.loads(r.output.replace("'",'"')) if False else r.output
 assert r.operation=="json_summary" and "'count': 3" in out and "'mean': 2.0" in out

def test_csv_summary_is_bounded():
 r=build_data_specialist(CapabilityRequest("DATA",data_operation="csv_summary")).analyze("a,b\n1,2\n3,4\n")
 assert r.operation=="csv_summary" and "'rows': 2" in r.output and "'columns': 2" in r.output

def test_unapproved_operation_rejected():
 with pytest.raises(PermissionError): build_data_specialist(CapabilityRequest("DATA",data_operation="python"))
 with pytest.raises(ValueError): build_data_specialist(CapabilityRequest())
