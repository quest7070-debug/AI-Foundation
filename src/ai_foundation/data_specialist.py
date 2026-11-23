from dataclasses import dataclass
from .capabilities import FixedComputeTool
@dataclass(frozen=True)
class DataResult:
    output: str
    operation: str
@dataclass
class DataSpecialist:
    compute_tool: FixedComputeTool
    def analyze(self,payload:str)->DataResult:
        return DataResult(str(self.compute_tool.run(payload)),self.compute_tool.operation)
