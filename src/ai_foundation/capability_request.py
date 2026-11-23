"""Trusted daily-use capability envelope. Authority is supplied by host context, never prompt text."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

_CAPABILITIES=frozenset({"CHAT","SEARCH","CODE","DATA","COMPUTE","FILES","BROWSER","PC_CONTROL","VISION"})

@dataclass(frozen=True)
class AttachmentGrant:
    attachment_id: str
    owner_id: str
    path: str
    def __post_init__(self):
        if not self.attachment_id or not self.owner_id: raise ValueError("attachment identity required")
        if not Path(self.path).is_absolute(): raise ValueError("attachment path must be host-resolved")

@dataclass(frozen=True)
class CapabilityRequest:
    capability: str = "CHAT"
    owner_id: str = ""
    repo_root: str = ""
    file_read_root: str = ""
    file_write_root: str = ""
    data_operation: str = ""
    data_backend: str = ""
    compute_profile: str = ""
    browser_target: str = ""
    pc_target: str = ""
    attachments: tuple[AttachmentGrant,...] = field(default_factory=tuple)
    long_running: bool = False
    attachment_ids: tuple[str,...] = field(default_factory=tuple)
    file_operation: str = "read"
    # Host-owned INPUT SHAPE, not a model authority grant. Default preserves
    # all pre-existing generic JSON summaries.
    data_value_contract: str = "any"

    def __post_init__(self):
        cap=self.capability.upper()
        if cap not in _CAPABILITIES: raise ValueError("unsupported capability")
        object.__setattr__(self,"capability",cap)
        if not isinstance(self.file_operation,str) or self.file_operation not in {"read","list_directory"}:
            raise ValueError("unsupported FILES operation")
        if self.file_operation != "read" and (cap != "FILES" or not self.file_read_root):
            raise ValueError("directory listing requires FILES with a trusted read root")
        if self.file_operation != "read" and self.attachments:
            raise ValueError("directory listing is unavailable in attachment mode")
        for name in ("repo_root","file_read_root","file_write_root"):
            value=getattr(self,name)
            if value and not Path(value).is_absolute(): raise ValueError(f"{name} must be host-resolved")
        if self.file_write_root:
            if not self.file_read_root: raise ValueError("write scope requires read scope")
            try: Path(self.file_write_root).resolve().relative_to(Path(self.file_read_root).resolve())
            except ValueError as e: raise PermissionError("write scope must be inside read scope") from e
        if self.attachments and not self.owner_id: raise ValueError("attachment owner required")
        if self.attachment_ids:
            if not self.owner_id: raise ValueError("attachment owner required")
            if len(self.attachment_ids)>10 or len(set(self.attachment_ids))!=len(self.attachment_ids) or any(not isinstance(x,str) or not x or len(x)>256 for x in self.attachment_ids): raise ValueError("invalid attachment ids")
        if any(a.owner_id != self.owner_id for a in self.attachments): raise PermissionError("attachment owner mismatch")
        if cap=="CODE" and not self.repo_root: raise ValueError("CODE requires trusted repo_root")
        if self.data_value_contract not in {"any","numeric_array"} or type(self.data_value_contract) is not str:
            raise ValueError("unsupported DATA input contract")
        if self.data_value_contract != "any" and self.data_operation != "json_summary":
            raise ValueError("numeric array contract requires authorized json_summary")
        if cap=="DATA" and not (self.data_operation or self.data_backend): raise ValueError("DATA requires bounded operation or trusted backend")
        if cap=="DATA" and self.data_operation and self.data_backend: raise ValueError("DATA deterministic operation and backend are mutually exclusive")
        if cap=="COMPUTE" and not self.compute_profile: raise ValueError("COMPUTE requires trusted compute profile")
        if cap=="FILES" and not (self.file_read_root or self.attachments):
            raise ValueError("FILES requires trusted read root or attachment grant")
        if cap=="BROWSER" and not self.browser_target: raise ValueError("BROWSER requires trusted target")
        if cap=="PC_CONTROL" and not self.pc_target: raise ValueError("PC_CONTROL requires trusted target")
        if cap=="VISION" and not (self.attachments or self.attachment_ids): raise ValueError("VISION requires trusted attachment")
