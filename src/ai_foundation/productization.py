import time
import hashlib,json,os,platform,shutil,sqlite3,tempfile
from dataclasses import dataclass,asdict
from pathlib import Path
from contextlib import closing
SCHEMA_VERSION=1
@dataclass(frozen=True)
class FoundationConfig:
    data_dir:str; trace_file:str='trace.jsonl'; guard_db:str='guard.db'; work_db:str='work.db'; provider_db:str='providers.sqlite'; routing_db:str='routing.sqlite'; reconciliation_db:str='reconciliation.sqlite'; inference_db:str='inference-attempts.sqlite'; toolhive_server:str='ai-foundation-fs'; schema_version:int=SCHEMA_VERSION
    def validate(self):
        if type(self.schema_version) is not int or self.schema_version!=SCHEMA_VERSION:raise ValueError('unsupported config schema')
        root=Path(self.data_dir).expanduser()
        if not root.is_absolute():raise ValueError('data_dir must be absolute')
        for name in (self.trace_file,self.guard_db,self.work_db,self.provider_db,self.routing_db,self.reconciliation_db,self.inference_db):
            p=Path(name)
            if p.is_absolute() or '..' in p.parts:raise ValueError('data filenames must stay under data_dir')
        return self
def save_config(config,path):config.validate();Path(path).write_text(json.dumps(asdict(config),indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def load_config(path):return FoundationConfig(**json.loads(Path(path).read_text(encoding='utf-8'))).validate()
def platform_capabilities():
    system=platform.system();return {'system':system,'machine':platform.machine(),'native_secret_store':system in {'Darwin'},'toolhive_supported':system in {'Darwin','Linux'}}
def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


class BackupValidationError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _unique_backup_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BackupValidationError('invalid-manifest', 'duplicate backup JSON field')
        result[key] = value
    return result


def _backup_file(root, name):
    candidate = root
    for part in Path(name).parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise BackupValidationError('unsafe-path', 'unsafe backup symbolic link')
    if not candidate.is_file():
        raise BackupValidationError('missing-file', 'backup file is missing or not regular')
    return candidate


def _backup_json(path):
    with path.open('rb') as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise BackupValidationError('invalid-manifest', 'backup JSON exceeds size limit')
    try:
        return json.loads(raw, object_pairs_hook=_unique_backup_fields)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise BackupValidationError('invalid-manifest', 'invalid backup JSON') from None


def _database_names(config):
    return (config.guard_db, config.work_db, config.provider_db,
        config.routing_db, config.reconciliation_db, config.inference_db)


def verify_backup(backup_dir):
    """Read-only v1 content verification shared by restore and generation retention.

    Hashes attest self-consistency, not provenance. SQLite is checked without
    sidecars or writes; application-level recovery still needs domain readback.
    """
    root = Path(backup_dir)
    if root.is_symlink() or not root.is_dir():
        raise BackupValidationError('unsafe-path', 'backup must be a real directory')
    manifest = _backup_json(_backup_file(root, 'manifest.json'))
    if not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int or manifest['schema_version'] != SCHEMA_VERSION:
        raise BackupValidationError('unsupported-schema', 'unsupported backup schema')
    files = manifest.get('files')
    if not isinstance(files, dict) or not 1 <= len(files) <= 1024:
        raise BackupValidationError('invalid-manifest', 'invalid backup file inventory')
    capture = manifest.get('capture')
    if 'capture' in manifest and (not isinstance(capture, dict)
            or capture.get('consistency') != 'per-file-snapshot'
            or type(capture.get('started_ns')) is not int or type(capture.get('ended_ns')) is not int
            or not 0 <= capture['started_ns'] <= capture['ended_ns']):
        raise BackupValidationError('invalid-manifest', 'invalid backup capture metadata')
    normalized = {}
    for name, digest in files.items():
        if not isinstance(name, str) or not name or '\0' in name:
            raise BackupValidationError('unsafe-path', 'unsafe backup manifest path')
        relative = Path(name)
        canonical = relative.as_posix()
        if relative.is_absolute() or '..' in relative.parts or canonical in {'.', 'manifest.json'} or canonical in normalized:
            raise BackupValidationError('unsafe-path', 'unsafe backup manifest path')
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise BackupValidationError('invalid-manifest', 'invalid backup file digest')
        normalized[canonical] = name
    if 'config.json' not in normalized:
        raise BackupValidationError('missing-config', 'backup configuration is missing')
    for name, digest in files.items():
        if sha256(_backup_file(root, name)) != digest:
            raise BackupValidationError('integrity', 'backup integrity check failed')
    try:
        config_data = _backup_json(_backup_file(root, normalized['config.json']))
        config = FoundationConfig(**config_data).validate()
    except (TypeError, ValueError):
        raise BackupValidationError('invalid-config', 'backup configuration is invalid') from None
    for name in _database_names(config):
        key = Path(name).as_posix()
        if key not in normalized:
            continue  # A fresh host may legitimately have no database yet.
        path = _backup_file(root, normalized[key])
        try:
            with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
                result = db.execute('PRAGMA quick_check').fetchall()
            if result != [('ok',)]:
                raise sqlite3.DatabaseError('quick_check failed')
        except sqlite3.DatabaseError:
            raise BackupValidationError('invalid-sqlite', 'backup SQLite integrity check failed') from None
    return manifest


def _publish_dir(stage,dest):
    if dest.exists():raise FileExistsError(f'destination already exists: {dest}')
    os.replace(stage,dest)
def backup(config,destination):
    config.validate();root=Path(config.data_dir);dest=Path(destination);dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists():raise FileExistsError(f'backup destination already exists: {dest}')
    stage=Path(tempfile.mkdtemp(prefix=f'.{dest.name}.staging-',dir=dest.parent));manifest={'schema_version':SCHEMA_VERSION,'files':{},'capture':{'started_ns':time.time_ns(),'ended_ns':None,'consistency':'per-file-snapshot'}}
    try:
        for name in (config.guard_db,config.work_db,config.provider_db,config.routing_db,config.reconciliation_db,config.inference_db,config.trace_file,'presentation.json','authority-initialized.json'):
            src=root/name
            if not src.exists():continue
            out=stage/name;out.parent.mkdir(parents=True,exist_ok=True)
            if name in _database_names(config):
                with closing(sqlite3.connect(src.resolve().as_uri()+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(out)) as target:
                    source.backup(target)
                    target.commit()
            else:shutil.copy2(src,out)
            manifest['files'][name]=sha256(out)
        save_config(config,stage/'config.json');manifest['files']['config.json']=sha256(stage/'config.json');manifest['capture']['ended_ns']=time.time_ns()
        (stage/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
        verify_backup(stage)
        _publish_dir(stage,dest);return manifest
    except Exception:
        shutil.rmtree(stage,ignore_errors=True);raise
def restore(backup_dir,destination,*,relocate_config=False):
    src=Path(backup_dir);dest=Path(destination)
    if dest.exists():raise FileExistsError(f'restore destination already exists: {dest}')
    manifest=verify_backup(src)
    dest.parent.mkdir(parents=True,exist_ok=True);stage=Path(tempfile.mkdtemp(prefix=f'.{dest.name}.staging-',dir=dest.parent))
    try:
        for name,digest in manifest['files'].items():
            target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src/name,target)
            if sha256(target)!=digest:raise ValueError('restore staging integrity check failed')
        if relocate_config and (stage/'config.json').exists():
            # Disaster recovery to a clean root needs a usable config for that root;
            # rollback restores keep the original path by leaving this opt-in false.
            original=load_config(stage/'config.json')
            save_config(FoundationConfig(**(asdict(original)|{'data_dir':str(dest.resolve())})),stage/'config.json')
        _publish_dir(stage,dest);return tuple(manifest['files'])
    except Exception:
        shutil.rmtree(stage,ignore_errors=True);raise


def portability_report(system=None,machine=None):
    system=system or platform.system();machine=machine or platform.machine()
    if system=='Darwin' and machine in {'arm64','aarch64'}:
        return {'host':f'{system}/{machine}','tier':'verified','native_secret_store':'macOS Keychain','notes':'real-M1 verified'}
    if system=='Linux':
        return {'host':f'{system}/{machine}','tier':'unsupported-unverified','native_secret_store':None,'notes':'ToolHive-capable boundary only; no native-secret adapter/real-host gate'}
    if system=='Windows':
        return {'host':f'{system}/{machine}','tier':'unsupported-unverified','native_secret_store':None,'notes':'Windows Credential Manager adapter not implemented/verified'}
    return {'host':f'{system}/{machine}','tier':'unsupported-unverified','native_secret_store':None,'notes':'no real-host verification'}
