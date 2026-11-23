"""Trusted host composition for capability execution shared by Operator and workers."""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from .toolhive import ToolHiveFilesystemPort,ToolHiveMCPClient,TOOLHIVE_FILESYSTEM_BINDING
from .mcp_capability import MCPToolGrant,MCPToolRegistry
from .capability_execution import CapabilityExecutor
from .protected_resources import production_protected_resources

@dataclass(frozen=True)
class CapabilityComposition:
 executor:CapabilityExecutor
 file_port:object
 repo_port:object|None
 tool_root:Path
 repo_root:Path|None

def build_capability_composition(*,repo_base,data_root,config,inference,guard,reconciliation_registry,activity=None,env=None,thv_path=None,vision_port=None):
 e=os.environ if env is None else env
 repo_base=Path(repo_base).resolve();data_root=Path(data_root).resolve()
 thv=Path(thv_path) if thv_path else repo_base/'.tools/toolhive/thv'
 tool_root=Path(e.get('AI_FOUNDATION_TOOLHIVE_ROOT','/tmp/ai-foundation-toolhive')).resolve()
 # The default FILES root lives under /tmp and may legitimately disappear on
 # macOS reboot. It is host-owned runtime state, so recreate only the directory;
 # ToolHive workload lifecycle remains owned by the canonical ensure path.
 tool_root.mkdir(parents=True,exist_ok=True)
 if not thv.exists():raise RuntimeError('ToolHive capability runtime unavailable')
 # Never default CODE to a versioned immutable Operator release checkout.
 # An exact workspace is a trusted host decision; missing binding disables
 # only CODE, not existing FILES/MCP or unrelated capabilities.
 repo_binding=e.get('AI_FOUNDATION_REPO_ROOT','')
 repo_root=None
 if repo_binding:
  requested=Path(repo_binding)
  if not requested.is_absolute() or '..' in requested.parts:
   raise ValueError('explicit absolute CODE workspace required')
  repo_root=requested.resolve(strict=True)
  if (not repo_root.is_dir() or repo_root==repo_base
      or repo_root in repo_base.parents or repo_base in repo_root.parents
      or repo_root==data_root or repo_root in data_root.parents
      or data_root in repo_root.parents):
   raise ValueError('CODE workspace must be distinct from Operator source and private data')
 file_port=ToolHiveFilesystemPort(thv,config.toolhive_server,tool_root)
 repo_port=(ToolHiveFilesystemPort(thv,e.get('AI_FOUNDATION_TOOLHIVE_REPO_SERVER','ai-foundation-repo'),repo_root)
            if repo_root is not None else None)
 mcp_registry=MCPToolRegistry(lambda server:ToolHiveMCPClient(thv,server))
 browser_server=e.get('AI_FOUNDATION_BROWSER_SERVER','').strip()
 compute_server=e.get('AI_FOUNDATION_COMPUTE_SERVER','').strip()
 data_server=e.get('AI_FOUNDATION_DATA_SERVER','').strip()
 if compute_server:
  mcp_registry.register(MCPToolGrant('compute-main',compute_server,frozenset({'execute_code'})))
 if data_server:
  mcp_registry.register(MCPToolGrant('data-duckdb',data_server,frozenset({
   'list_tables','describe_table','profile_table','sample_rows','query',
   'explain_query','search_columns','table_relationships',
  })))
 if browser_server:
  mcp_registry.register(MCPToolGrant('browser-main',browser_server,frozenset({
   'browser_console_messages','browser_network_request','browser_network_requests',
   'browser_snapshot','browser_take_screenshot','browser_wait_for',
  })))
 executor=CapabilityExecutor(inference,guard,file_port,reconciliation_registry,TOOLHIVE_FILESYSTEM_BINDING,production_protected_resources(data_root),activity,repo_port=repo_port,repo_port_binding='toolhive:repo',vision_port=vision_port,mcp_registry=mcp_registry)
 return CapabilityComposition(executor,file_port,repo_port,tool_root,repo_root)
