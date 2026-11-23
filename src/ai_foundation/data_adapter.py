"""Bounded local DATA operations. Operation authority comes only from CapabilityRequest."""
from __future__ import annotations
import csv,io,json,statistics
from .capabilities import BoundComputeCapability,FixedComputeTool
from .capability_request import CapabilityRequest
from .data_specialist import DataSpecialist

_ALLOWED=frozenset({"json_summary","csv_summary"})

class BoundedDataPort:
    def compute(self,operation:str,payload:str):
        if operation=="json_summary":
            data=json.loads(payload)
            if isinstance(data,dict):
                return {"type":"object","count":len(data),"keys":list(data)[:100]}
            if isinstance(data,list):
                nums=[float(x) for x in data if isinstance(x,(int,float)) and not isinstance(x,bool)]
                out={"type":"array","count":len(data)}
                if nums: out.update({"numeric_count":len(nums),"min":min(nums),"max":max(nums),"mean":statistics.fmean(nums)})
                return out
            return {"type":type(data).__name__,"value":data}
        if operation=="csv_summary":
            rows=list(csv.reader(io.StringIO(payload)))
            if not rows:return {"rows":0,"columns":0}
            width=max(map(len,rows))
            return {"rows":max(0,len(rows)-1),"columns":width,"header":rows[0][:100]}
        raise PermissionError("unsupported data operation")

def build_data_specialist(request:CapabilityRequest)->DataSpecialist:
    if request.capability!="DATA": raise ValueError("DATA capability required")
    if request.data_operation not in _ALLOWED: raise PermissionError("data operation not host-allowed")
    capability=BoundComputeCapability(BoundedDataPort(),frozenset({request.data_operation}))
    return DataSpecialist(FixedComputeTool(capability,request.data_operation))
