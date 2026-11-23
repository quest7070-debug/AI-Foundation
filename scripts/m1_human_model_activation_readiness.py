"""Read-only M1 readiness: existing owner, approved view, installed runtime.

No view creation/rebuild, private import, config write, model invocation,
service restart or Native dispatch. Public output contains counters/booleans.
"""
from __future__ import annotations
import ast
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def existing_ledger_roots(volumes=Path('/Volumes'), *, mounted=os.path.ismount, info=None):
    if info is None:
        def info(path):
            cp=subprocess.run(['/usr/sbin/diskutil','info','-plist',str(path)],capture_output=True,timeout=10,check=True)
            return plistlib.loads(cp.stdout)
    roots=[]
    for mount in volumes.iterdir():
        if mount.is_symlink() or not mount.is_dir() or not mounted(str(mount)): continue
        root=mount/'HumanModel'
        ledger=root/'ledger'/'human_model.sqlite3'
        # Avoid executing diskutil on every unrelated mount (some mounts
        # reject diskutil info and previously aborted the entire probe).
        # A mount with a candidate ledger MUST still pass diskutil exactly:
        # errors there remain fail-closed; never infer a trusted root.
        if root.is_symlink() or not ledger.is_file() or ledger.is_symlink(): continue
        row=info(mount)
        if row.get('Internal') is not False or row.get('BusProtocol')!='USB' or row.get('MountPoint')!=str(mount): continue
        roots.append(root)
    return roots


def inspect_ledger(root, binding=None):
    from ai_foundation.human_model_context import _source_reader
    read=_source_reader(ROOT)
    module=__import__(read.__module__.rsplit('.',1)[0]+'.storage_location',fromlist=['validated_ledger_path'])
    path=module.validated_ledger_path(root)
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        if db.execute('PRAGMA quick_check').fetchone()!=('ok',): raise ValueError('ledger integrity')
        evidence=db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]
        rows=db.execute('SELECT id,audience,allowed_scopes,max_privacy,revision,stale FROM model_views').fetchall()
        eligible=[]; stale=0
        for view,audience,scopes,privacy,revision,is_stale in rows:
            if audience!='foundation': continue
            if is_stale: stale+=1;continue
            parsed=json.loads(scopes)
            if (type(revision) is not int or revision<1 or privacy not in {'private','restricted','shareable'}
                    or not isinstance(parsed,list) or not parsed or any(not isinstance(s,str) or not s or s=='*' for s in parsed)):
                continue
            count=db.execute('SELECT COUNT(*) FROM model_sources WHERE model_id=?',(view,)).fetchone()[0]
            if binding is not None:
                levels={'shareable':0,'restricted':1,'private':2}
                if (view!=binding.view_id or not set(binding.scopes)<=set(parsed)
                        or levels[binding.max_privacy]>levels[privacy]):continue
                parsed=list(binding.scopes);privacy=binding.max_privacy
            if count: eligible.append((view,parsed,privacy,revision,count))
        summary={'evidence_count':evidence,'view_count':len(rows),'stale_foundation_views':stale,
                 'eligible_nonempty_views':len(eligible),'source_snapshot_verified':False}
    finally:db.close()
    if len(eligible)==1:
        view,scopes,privacy,revision,_=eligible[0]
        for scope in scopes:
            snapshot=read(root,view_id=view,scope=scope,max_privacy=privacy)
            if snapshot['view_revision']!=revision: raise ValueError('view revision drift')
            if snapshot['records']:
                summary['source_snapshot_verified']=True;break
    return summary


def _owner_record(docker):
    # Only server-side account identity; never emails, names, passwords or tokens.
    code="const a=db.users.find({},{_id:1}).limit(2).toArray();print(JSON.stringify({count:a.length,owner:a.length===1?String(a[0]._id):null}));"
    cp=subprocess.run([docker,'exec','chat-mongodb','mongosh','--quiet','LibreChat','--eval',code],
                      capture_output=True,text=True,timeout=15,check=True)
    lines=[line for line in cp.stdout.splitlines() if line.startswith('{')]
    if len(lines)!=1:raise ValueError('owner query response')
    return json.loads(lines[0])


def inspect_owner(docker):
    row=_owner_record(docker)
    return {'single_server_owner':row.get('count')==1 and isinstance(row.get('owner'),str)
            and re.fullmatch('[0-9a-fA-F]{24}',row['owner']) is not None}

_OWNER_PROBE_STATES = frozenset({
    'CONTAINER_RUNNING_QUERY_FAILED', 'CONTAINER_STOPPED',
    'CONTAINER_UNAVAILABLE_DAEMON_OK', 'DOCKER_DAEMON_INACCESSIBLE',
    'DOCKER_INSPECT_UNAVAILABLE',
})


def _owner_service_state(docker):
    """Bounded, read-only fixed container state; no account/config/log export.

    Called only when the established mongosh owner query has failed. Docker
    inspect returns the literal running bit, not the container definition.
    """
    try:
        cp=subprocess.run(
            [docker,'inspect','--format','{{.State.Running}}','chat-mongodb'],
            capture_output=True,text=True,timeout=8,check=False,
        )
    except (OSError,subprocess.TimeoutExpired):
        return 'DOCKER_INSPECT_UNAVAILABLE'
    if cp.returncode:
        # A failed container inspect can mean the daemon is not available,
        # rather than that the named container is missing. Check only server
        # accessibility with a fixed read-only command. Never inspect configs.
        try:
            daemon=subprocess.run(
                [docker,'info','--format','{{.ServerVersion}}'],
                capture_output=True,text=True,timeout=8,check=False,
            )
        except (OSError,subprocess.TimeoutExpired):
            return 'DOCKER_DAEMON_INACCESSIBLE'
        if daemon.returncode == 0 and daemon.stdout.strip():
            return 'CONTAINER_UNAVAILABLE_DAEMON_OK'
        return 'DOCKER_DAEMON_INACCESSIBLE'
    flag=cp.stdout.strip()
    if flag=='true': return 'CONTAINER_RUNNING_QUERY_FAILED'
    if flag=='false': return 'CONTAINER_STOPPED'
    return 'DOCKER_INSPECT_UNAVAILABLE'


def _installed_operator_binding(home):
    """Resolve only the trusted fixed Operator plist, no guesswork from script name.

    The active packaged Operator may use a versioned/renamed Python launcher.
    We accept exactly one absolute Python script and the same explicit
    --config argument, never shell, -c/-m or an inferred data root.
    """
    import stat
    plist=home/'Library/LaunchAgents/dev.quest7070.ai-foundation.operator.plist'
    try:
        if plist.is_symlink() or not plist.is_file(): return None
        info=plist.stat()
        if info.st_uid!=os.getuid() or info.st_mode & 0o022: return None
        row=plistlib.loads(plist.read_bytes())
        if type(row) is not dict or row.get('Label')!='dev.quest7070.ai-foundation.operator':
            return None
        args=row.get('ProgramArguments')
        if (type(args) is not list or not 1<=len(args)<=24
                or any(type(arg) is not str or len(arg)>4096 for arg in args)
                or any(arg in ('-c','-m','--') for arg in args)):
            return None
        scripts=[Path(arg) for arg in args if arg.startswith('/') and arg.endswith('.py')]
        if len(scripts)!=1 or '..' in scripts[0].parts: return None
        script=scripts[0]
        if script.is_symlink() or not script.is_file(): return None
        info=script.stat()
        if info.st_uid!=os.getuid() or info.st_mode & 0o022 or not stat.S_ISREG(info.st_mode):
            return None
        if args.count('--config')!=1 or args.index('--config')+1>=len(args):
            return (script,None)
        working=Path(row.get('WorkingDirectory','/'))
        if not working.is_absolute() or '..' in working.parts:return (script,None)
        config_path=Path(args[args.index('--config')+1])
        if not config_path.is_absolute():config_path=working/config_path
        if '..' in config_path.parts or config_path.is_symlink() or not config_path.is_file():
            return (script,None)
        info=config_path.stat()
        if info.st_uid!=os.getuid() or info.st_mode & 0o022 or info.st_size>65536:
            return (script,None)
        raw=json.loads(config_path.read_text())
        if type(raw) is not dict or type(raw.get('data_dir')) is not str:
            return (script,None)
        data=Path(raw['data_dir']).expanduser()
        if not data.is_absolute():data=working/data
        if '..' in data.parts or not data.is_dir():return (script,None)
        data=data.resolve(strict=True)
        if data.is_symlink() or data.stat().st_uid!=os.getuid():
            return (script,None)
        return script,data
    except (OSError,ValueError,KeyError,TypeError,plistlib.InvalidFileException):
        return None


def installed_paths(home=Path.home()):
    entry=_installed_operator_binding(home)
    return entry if entry and entry[1] is not None else None


def _loader_source_kind(script):
    """Structural on-disk evidence only, never loaded-process attestation.

    Imported symbol AND a real call are required. Bare strings, comments and
    stale source files cannot make a synthetic approval or grant.
    """
    import stat
    try:
        if script.is_symlink() or not script.is_file():return "UNVERIFIED"
        info=script.stat()
        if (info.st_uid!=os.getuid() or info.st_mode & 0o022
                or not stat.S_ISREG(info.st_mode) or info.st_size>262144):
            return "UNVERIFIED"
        tree=ast.parse(script.read_text(encoding="utf-8"))
        imports=set()
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom) and node.module in (
                    "ai_foundation.human_model_runtime",
                    "ai_foundation.human_model_context"):
                imports.update(a.name for a in node.names)
        calls={node.func.id for node in ast.walk(tree)
               if isinstance(node,ast.Call) and isinstance(node.func,ast.Name)}
        if "install_legacy_agent_factory" in imports and "install_legacy_agent_factory" in calls:
            return "ADDITIVE_LAUNCHER_SOURCE"
        if "build_human_model_context" in imports and "build_human_model_context" in calls:
            return "DIRECT_OPERATOR_SOURCE"
    except (OSError,ValueError,SyntaxError,UnicodeError):
        pass
    return "UNVERIFIED"


def inspect_installed_runtime(home=Path.home()):
    result={'operator_source_identified':False,'installed_context_code':False,
            'installed_binding_loader':False,'loader_source_kind':'UNVERIFIED',
            'existing_binding_config':False,'loaded_process_verified':False}
    entry=_installed_operator_binding(home)
    if entry is None:return result
    script,data=entry
    result['operator_source_identified']=True
    result['loader_source_kind']=_loader_source_kind(script)
    result['installed_binding_loader']=result['loader_source_kind']!='UNVERIFIED'
    if data is None:return result
    source=script.parent.parent
    result['installed_context_code']=(source/'src/ai_foundation/human_model_context.py').is_file()
    result['existing_binding_config']=(data/'human-model-bindings.json').is_file()
    # Never claim live loaded-process or model-tool-loop proof from disk.
    return result


def blockers(report):
    out=[]
    if report.get('ledger_candidates')!=1:out.append('EXISTING_EXTERNAL_LEDGER_NOT_UNIQUE')
    ledger=report.get('ledger',{})
    if ledger.get('evidence_count',0)==0:out.append('NO_HUMANMODEL_EVIDENCE')
    if ledger.get('eligible_nonempty_views')!=1:out.append('APPROVED_NONEMPTY_VIEW_NOT_UNIQUE')
    elif not ledger.get('source_snapshot_verified'):out.append('APPROVED_SOURCE_SNAPSHOT_UNVERIFIED')
    if not report.get('identity',{}).get('single_server_owner'):out.append('SERVER_OWNER_NOT_UNIQUE')
    if report.get('identity',{}).get('binding_owner_matches') is False:
        out.append('SERVER_OWNER_BINDING_MISMATCH')
    runtime=report.get('runtime',{})
    if not (runtime.get('installed_context_code') and runtime.get('installed_binding_loader')):
        out.append('CANONICAL_RELEASE_REQUIRES_CONTEXT_INTEGRATION')
    return out


def main():
    report={'diagnostic_complete':False,'activation_permitted':False,'mutations':0,
            'native_dispatches':0,'private_content_logged':False}
    try:
        if sys.platform!='darwin':raise RuntimeError('M1_HOST_REQUIRED')
        docker=shutil.which('docker') or next((p for p in ('/usr/local/bin/docker','/opt/homebrew/bin/docker') if Path(p).is_file()),None)
        if not docker:raise RuntimeError('DOCKER_UNAVAILABLE')
        roots=existing_ledger_roots();report['ledger_candidates']=len(roots)
        try:
            account=_owner_record(docker)
        except subprocess.CalledProcessError:
            report['owner_service_state']=_owner_service_state(docker)
            raise
        owner=account.get('owner')
        report['identity']={'single_server_owner':account.get('count')==1 and isinstance(owner,str)
                            and re.fullmatch('[a-fA-F0-9]{24}',owner) is not None}
        binding=None;paths=installed_paths()
        if paths is not None:
            from ai_foundation.human_model_context import load_bindings
            bindings=load_bindings(paths[1]/'human-model-bindings.json')
            if bindings:
                binding=bindings.get(owner)
                report['identity']['binding_owner_matches']=binding is not None
        if len(roots)==1:
            if binding is not None and Path(binding.root).resolve()!=roots[0].resolve():
                raise ValueError('bound source root differs')
            report['ledger']=inspect_ledger(roots[0],binding)
        report['runtime']=inspect_installed_runtime()
        report['blockers']=blockers(report)
        report['binding_prerequisites_ready']=not any(code in report['blockers'] for code in (
            'EXISTING_EXTERNAL_LEDGER_NOT_UNIQUE','NO_HUMANMODEL_EVIDENCE','APPROVED_NONEMPTY_VIEW_NOT_UNIQUE',
            'APPROVED_SOURCE_SNAPSHOT_UNVERIFIED','SERVER_OWNER_NOT_UNIQUE','SERVER_OWNER_BINDING_MISMATCH'))
        report['diagnostic_complete']=True
        report['status']=('BLOCKED' if report['blockers'] else
            'CONTEXT_CODE_AND_SOURCE_READY' if report['runtime']['existing_binding_config'] else 'READY_FOR_REVIEWED_BINDING')
        print(json.dumps(report,sort_keys=True));return 0
    except Exception as exc:
        report['status']='BLOCKED';report['error_type']=type(exc).__name__
        print(json.dumps(report,sort_keys=True));return 2


if __name__=='__main__':raise SystemExit(main())
