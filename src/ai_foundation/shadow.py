"""Phase-H shadow evidence. Comparison only: never executes or changes authority."""
from dataclasses import dataclass,asdict
import json,time,os
from enum import Enum
from pathlib import Path

_FIELDS=('route_kind','route_label','status','verification','output')
REQUIRED_H3_PATHS=('local-inference','cloud-inference','human-approval','human-input','cancellation','tool-effect','uncertain-recovery','provider-failover')
class EvidenceClass(str,Enum):
 LIVE='LIVE'
 ISOLATED_REAL='ISOLATED_REAL'
 DETERMINISTIC='DETERMINISTIC'
MIN_H3_EVIDENCE={
 'local-inference':EvidenceClass.LIVE,
 'cloud-inference':EvidenceClass.LIVE,
 'human-approval':EvidenceClass.DETERMINISTIC,
 'human-input':EvidenceClass.DETERMINISTIC,
 'cancellation':EvidenceClass.DETERMINISTIC,
 'tool-effect':EvidenceClass.ISOLATED_REAL,
 'uncertain-recovery':EvidenceClass.ISOLATED_REAL,
 'provider-failover':EvidenceClass.DETERMINISTIC,
}
_EVIDENCE_RANK={EvidenceClass.DETERMINISTIC:1,EvidenceClass.ISOLATED_REAL:2,EvidenceClass.LIVE:3}
@dataclass(frozen=True)
class ShadowObservation:
 path:str; route_kind:str|None; route_label:str|None; status:str; verification:str; output:str|None=None
@dataclass(frozen=True)
class ShadowComparison:
 path:str; equivalent:bool; differences:tuple[str,...]; observed_at:float
@dataclass(frozen=True)
class ShadowGate:
 path:str; passed:bool; samples:int; mismatches:int; required_samples:int; fields:tuple[str,...]=_FIELDS

@dataclass(frozen=True)
class ShadowMatrixGate:
 passed:bool; gates:tuple[ShadowGate,...]; missing:tuple[str,...]

def compare(candidate:ShadowObservation,baseline:ShadowObservation):
 if candidate.path!=baseline.path: raise ValueError('shadow paths differ')
 diff=tuple(f for f in _FIELDS if getattr(candidate,f)!=getattr(baseline,f))
 return ShadowComparison(candidate.path,not diff,diff,time.time())

def append_evidence(path,candidate,baseline,evidence_class=EvidenceClass.DETERMINISTIC):
 result=compare(candidate,baseline);p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
 evidence_class=EvidenceClass(evidence_class)
 row={'schema':2,'authority':'shadow-only','evidence_class':evidence_class.value,'candidate':asdict(candidate),'baseline':asdict(baseline),'comparison':asdict(result)}
 # One append call per JSONL record. Shadow evidence is deliberately separate from operational authority stores.
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
 try:
  os.write(fd,(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n').encode());os.fsync(fd)
 finally:os.close(fd)
 return result

def read_evidence(path):
 p=Path(path)
 if not p.exists():return ()
 rows=[]
 for line_no,line in enumerate(p.read_text(encoding='utf-8').splitlines(),1):
  try:row=json.loads(line)
  except json.JSONDecodeError as e:raise ValueError(f'corrupt shadow evidence line {line_no}') from e
  if row.get('schema')!=2 or row.get('authority')!='shadow-only' or row.get('evidence_class') not in {x.value for x in EvidenceClass}:raise ValueError(f'unsupported shadow evidence line {line_no}')
  rows.append(row)
 return tuple(rows)

def gate(path,evidence_path,required_samples=3,min_evidence_class=None):
 if required_samples<1:raise ValueError('required_samples must be positive')
 rows=[r for r in read_evidence(evidence_path) if r['comparison']['path']==path]
 if min_evidence_class is not None:
  floor=_EVIDENCE_RANK[EvidenceClass(min_evidence_class)]
  rows=[r for r in rows if _EVIDENCE_RANK[EvidenceClass(r['evidence_class'])]>=floor]
 mismatches=sum(not r['comparison']['equivalent'] for r in rows)
 return ShadowGate(path,len(rows)>=required_samples and mismatches==0,len(rows),mismatches,required_samples)


def gate_matrix(paths,evidence_path,required_samples=3):
 paths=tuple(paths)
 if not paths: raise ValueError('paths required')
 if len(paths)!=len(set(paths)): raise ValueError('duplicate paths')
 gates=tuple(gate(path,evidence_path,required_samples,MIN_H3_EVIDENCE.get(path)) for path in paths)
 missing=tuple(g.path for g in gates if g.samples < required_samples)
 return ShadowMatrixGate(all(g.passed for g in gates),gates,missing)

def h3_gate(evidence_path,required_samples=3):
 return gate_matrix(REQUIRED_H3_PATHS,evidence_path,required_samples)

def h3_status(evidence_path,required_samples=3):
 g=h3_gate(evidence_path,required_samples)
 return {x.path:{'passed':x.passed,'samples':x.samples,'mismatches':x.mismatches,'required_samples':x.required_samples} for x in g.gates}

@dataclass(frozen=True)
class H3PathReport:
 path:str; state:str; samples:int; mismatches:int; required_samples:int; reason:str|None=None

def h3_report(evidence_path,blocked=None,required_samples=3):
 # BLOCKED/NOT_RUN are reporting states only; they never create evidence or PASS.
 blocked=dict(blocked or {})
 status=h3_status(evidence_path,required_samples)
 out=[]
 for path in REQUIRED_H3_PATHS:
  x=status[path]
  if x['mismatches']: state,reason='MISMATCH',None
  elif x['passed']: state,reason='PASS',None
  elif path in blocked: state,reason='BLOCKED',str(blocked[path])
  else: state,reason='NOT_RUN',None
  out.append(H3PathReport(path,state,x['samples'],x['mismatches'],x['required_samples'],reason))
 return tuple(out)
