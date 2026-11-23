"""Canonical host registration/selection boundary for generic MCP tools."""
from __future__ import annotations
from dataclasses import dataclass
from .toolhive import BoundMCPTools

@dataclass(frozen=True)
class MCPToolGrant:
 name:str
 server:str
 allowed_tools:frozenset[str]
 def __post_init__(self):
  if not self.name or not self.server or not self.allowed_tools: raise ValueError('invalid MCP grant')

class MCPToolRegistry:
 def __init__(self,client_factory):self.client_factory=client_factory;self._grants={}
 def register(self,grant):
  if grant.name in self._grants: raise ValueError('duplicate MCP grant')
  self._grants[grant.name]=grant
 def select(self,name):
  try:g=self._grants[name]
  except KeyError as e:raise PermissionError('MCP grant not registered') from e
  return BoundMCPTools(self.client_factory(g.server),g.allowed_tools)
 def invoke(self,name,tool,args):return self.select(name).call(tool,args)
