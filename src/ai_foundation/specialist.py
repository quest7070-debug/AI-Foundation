from dataclasses import dataclass
from .capabilities import FixedComputeTool
@dataclass
class TextAnalysisSpecialist:
    """First narrow specialist: methodology over a host-bound compute capability."""
    summarize_tool: FixedComputeTool
    def summarize(self, text: str):
        return self.summarize_tool.run(text)
