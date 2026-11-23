import json, subprocess, threading, time
from pathlib import Path
from .core import TaskPlan

TOOLHIVE_FILESYSTEM_BINDING='toolhive:filesystem'

class ToolHiveFilesystemPort:
    """Narrow ExecutionPort over a preconfigured ToolHive filesystem workload."""
    def __init__(self, thv: str|Path, server: str, host_root: str|Path, container_root: str='/projects'):
        self.thv=str(thv); self.server=server; self.host_root=Path(host_root).resolve(); self.container_root=container_root.rstrip('/'); self._restart_lock=threading.Lock()

    def _paths(self, target: str):
        host=Path(target).resolve()
        try: rel=host.relative_to(self.host_root)
        except ValueError as e: raise ValueError('target outside ToolHive mount') from e
        return host, f"{self.container_root}/{rel.as_posix()}"

    def _invoke(self, tool, args):
        return subprocess.run([self.thv,'mcp','call',tool,'--server',self.server,'--format','json','--args',json.dumps(args)],capture_output=True,text=True,timeout=30)

    def _wait_running(self, timeout=10.0):
        # Use ToolHive v0.49's structured status output, not a tabwriter or
        # an indicator string. Require the exact host-selected workload name.
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            try:
                cp=subprocess.run([self.thv,'status',self.server,'--format','json'],
                                  capture_output=True,text=True,
                                  timeout=max(.1,min(3.0,end-time.monotonic())))
            except (OSError,subprocess.TimeoutExpired):
                return False
            if cp.returncode==0 and isinstance(cp.stdout,str) and len(cp.stdout)<=8192:
                try: row=json.loads(cp.stdout)
                except (ValueError,TypeError): row=None
                if (type(row) is dict and row.get('name')==self.server
                        and row.get('status')=='running'):
                    return True
            if time.monotonic()<end: time.sleep(.2)
        return False

    def _call(self, tool, args):
        cp=self._invoke(tool,args)
        if cp.returncode:
            if tool == 'write_file':
                # A nonzero CLI result may follow a successful remote write.
                # Never redispatch an effect before Guard's independent readback.
                raise RuntimeError('ToolHive MCP call failed')
            # Only the two fixed read-only filesystem tools may refresh a
            # stale ToolHive proxy and retry under the existing port lock.
            if tool not in {'read_text_file', 'list_directory'}:
                raise RuntimeError('ToolHive MCP call failed')
            with self._restart_lock:
                if not self._wait_running():
                    raise RuntimeError('ToolHive MCP call failed')
                cp=self._invoke(tool,args)
            if cp.returncode:
                raise RuntimeError('ToolHive MCP call failed')
        try:return json.loads(cp.stdout)
        except json.JSONDecodeError as e: raise RuntimeError('ToolHive MCP returned invalid JSON') from e

    def execute(self, plan: TaskPlan):
        _, remote=self._paths(plan.target)
        if plan.action != 'write': raise ValueError('unsupported ToolHive effect')
        self._call('write_file',{'path':remote,'content':plan.text})

    def observe(self, plan: TaskPlan):
        host,remote=self._paths(plan.target)
        if plan.action == 'list_directory':
            if not host.is_dir(): raise NotADirectoryError('listing target is not a directory in the bound scope')
            result=self._call('list_directory',{'path':remote})
            if not isinstance(result,dict) or type(result.get('isError',False)) is not bool or result.get('isError',False):
                raise RuntimeError('ToolHive directory listing failed')
            content=result.get('content')
            if not isinstance(content,list) or not 1<=len(content)<=32:
                raise RuntimeError('ToolHive returned invalid directory listing')
            chunks=[];size=0
            for chunk in content:
                if not isinstance(chunk,dict) or chunk.get('type')!='text' or not isinstance(chunk.get('text'),str):
                    raise RuntimeError('ToolHive returned invalid directory listing')
                text=chunk['text']
                # Bound the text exposed to the Agent; the MCP server owns directory
                # enumeration. Never truncate into a misleading partial listing.
                if len(text)>32768:raise RuntimeError('directory listing exceeds 32 KiB; choose a narrower directory')
                try:size+=len(text.encode('utf-8'))
                except UnicodeError as error:raise RuntimeError('ToolHive returned invalid directory listing') from error
                if size>32768:raise RuntimeError('directory listing exceeds 32 KiB; choose a narrower directory')
                chunks.append(text)
            return ''.join(chunks)
        if not host.exists(): raise FileNotFoundError(f'file not found in bound scope: {host.name}')
        result=self._call('read_text_file',{'path':remote})
        if not isinstance(result, dict) or type(result.get('isError', False)) is not bool or result.get('isError', False):
            raise RuntimeError('ToolHive file read failed')
        chunks=result.get('content')
        if not isinstance(chunks, list) or not chunks or any(
            not isinstance(x, dict) or x.get('type') != 'text' or not isinstance(x.get('text'), str)
            for x in chunks
        ):
            raise RuntimeError('ToolHive returned invalid file read')
        return ''.join(x['text'] for x in chunks)

class ToolHiveMCPClient:
    """Generic MCP protocol client through one host-selected ToolHive workload.

    Server identity is constructor-bound. Callers may use only tools discovered
    from that server; they cannot select/register another workload at call time.
    """
    def __init__(self, thv: str|Path, server: str, timeout: float=30):
        if not server or any(c.isspace() for c in server):
            raise ValueError('invalid ToolHive server')
        self.thv=str(thv); self.server=server; self.timeout=timeout

    def _run(self, argv):
        cp=subprocess.run([self.thv,'mcp',*argv,'--server',self.server,'--format','json'],
                          capture_output=True,text=True,timeout=self.timeout)
        if cp.returncode:
            raise RuntimeError('ToolHive MCP operation failed')
        try: return json.loads(cp.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError('ToolHive MCP returned invalid JSON') from e

    def discover(self):
        result=self._run(['list'])
        tools=result.get('tools',[])
        if not isinstance(tools,list): raise RuntimeError('invalid MCP tool inventory')
        out={}
        for item in tools:
            if isinstance(item,dict) and isinstance(item.get('name'),str):
                out[item['name']]=item
        return out

    def call(self, tool: str, args: dict):
        if not isinstance(tool,str) or not tool or not isinstance(args,dict):
            raise ValueError('invalid MCP call')
        if tool not in self.discover():
            raise ValueError('unknown MCP tool')
        return self._run(['call',tool,'--args',json.dumps(args,separators=(',',':'))])


class BoundMCPTools:
    """Run-scoped generic MCP exposure. Server and allowed tool names are host-bound."""
    def __init__(self, client: ToolHiveMCPClient, allowed_tools):
        self.client=client; self.allowed=frozenset(allowed_tools)
        if not self.allowed: raise ValueError('empty MCP tool scope')
    def inventory(self):
        live=self.client.discover()
        return {name:live[name] for name in self.allowed if name in live}
    def call(self, tool: str, args: dict):
        if tool not in self.allowed: raise PermissionError('MCP tool outside bound scope')
        # ToolHiveMCPClient re-discovers immediately before dispatch, so a tool
        # removed after this run was constructed cannot retain stale authority.
        return self.client.call(tool,args)
