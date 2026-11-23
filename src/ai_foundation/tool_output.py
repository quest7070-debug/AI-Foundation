from dataclasses import dataclass

@dataclass(frozen=True)
class ToolObservation:
    value: str
    source: str = "tool"
    trusted_as_authority: bool = False

def untrusted_tool_text(value: str) -> ToolObservation:
    """External/tool text is evidence/data, never authority or instructions."""
    return ToolObservation(value=value, trusted_as_authority=False)
