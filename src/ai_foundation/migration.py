import json,shutil,os,tempfile,time
from dataclasses import dataclass
from pathlib import Path
from .productization import FoundationConfig,backup,restore,sha256,SCHEMA_VERSION

def _journal_path(config): return Path(config.data_dir).parent/f'.{Path(config.data_dir).name}.update-journal.json'
def _write_journal(config,status,**extra):
    path=_journal_path(config);row={'status':status,'updated_at':time.time(),**extra};path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.update-journal-',text=True)
    try:
        with os.fdopen(fd,'w') as f: json.dump(row,f);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return path
def read_update_journal(config):
    p=_journal_path(config)
    if not p.exists(): return None
    try:
        row=json.loads(p.read_text())
    except (OSError,json.JSONDecodeError) as exc: raise UpdateRollbackError('update journal unreadable') from exc
    if row.get('status') not in {'APPLYING','VERIFIED','ROLLED_BACK'}: raise UpdateRollbackError('update journal status invalid')
    return row

@dataclass(frozen=True)
class MigrationResult: from_version:int;to_version:int;backup_dir:str;changed:bool
@dataclass(frozen=True)
class UpdateResult: status:str;backup_dir:str;applied:bool;rolled_back:bool
class UpdateRollbackError(RuntimeError):pass
class Migrator:
    def __init__(self,current=SCHEMA_VERSION):self.current=current
    def migrate(self,config,backup_dir):
        config.validate()
        if config.schema_version==self.current:return MigrationResult(self.current,self.current,str(backup_dir),False)
        raise ValueError('unsupported migration path')
def staged_update_preflight(config,stage_dir):
    config.validate();stage=Path(stage_dir)
    if stage.exists() and any(stage.iterdir()):raise ValueError('stage directory must be empty')
    return True
def verify_update_package(package_dir):
    root=Path(package_dir);row=json.loads((root/'update-manifest.json').read_text(encoding='utf-8'))
    if row.get('schema_version')!=SCHEMA_VERSION:raise ValueError('unsupported update schema')
    files=row.get('files')
    if not isinstance(files,dict) or not files:raise ValueError('invalid update manifest')
    for name,digest in files.items():
        p=Path(name)
        if p.is_absolute() or '..' in p.parts or name=='update-manifest.json':raise ValueError('invalid update path')
        target=root/p
        if not target.is_file() or sha256(target)!=digest:raise ValueError('update integrity check failed')
    return row
def apply_update_transaction(config,package_dir,backup_dir,apply_fn,readback_fn,rollback_dir):
    config.validate();verify_update_package(package_dir);live=Path(config.data_dir);backup_dir=Path(backup_dir);rollback_dir=Path(rollback_dir)
    if backup_dir.exists() or rollback_dir.exists():raise FileExistsError('update backup/rollback destination already exists')
    backup(config,backup_dir)
    _write_journal(config,'APPLYING',backup_dir=str(backup_dir),package_dir=str(package_dir))
    try:
        apply_fn(Path(package_dir))
        if not bool(readback_fn()):raise RuntimeError('update readback failed')
        _write_journal(config,'VERIFIED',backup_dir=str(backup_dir))
        return UpdateResult('VERIFIED',str(backup_dir),True,False)
    except Exception as original:
        quarantine=live.parent/f'.{live.name}.failed-update'
        try:
            if live.exists():
                if quarantine.exists():raise UpdateRollbackError('rollback quarantine already exists')
                live.replace(quarantine)
            restore(backup_dir,rollback_dir);rollback_dir.replace(live)
        except Exception as rollback_error:
            detail=str(rollback_error) if isinstance(rollback_error,UpdateRollbackError) else type(rollback_error).__name__
            raise UpdateRollbackError(f'update failed and rollback failed ({detail}); backup={backup_dir}; quarantine={quarantine}') from rollback_error
        else:
            shutil.rmtree(quarantine,ignore_errors=True);_write_journal(config,'ROLLED_BACK',backup_dir=str(backup_dir))
        raise original

@dataclass(frozen=True)
class UpdateRecoveryState:
    status:str;backup_present:bool;quarantine_present:bool;live_present:bool

def inspect_interrupted_update(config,backup_dir):
    config.validate();live=Path(config.data_dir);backup_dir=Path(backup_dir);quarantine=live.parent/f'.{live.name}.failed-update'
    backup_present=(backup_dir/'manifest.json').is_file()
    quarantine_present=quarantine.exists();live_present=live.exists()
    if quarantine_present and not live_present:status='RECOVERY_REQUIRED'
    elif quarantine_present and live_present:status='MANUAL_RECONCILIATION_REQUIRED'
    elif backup_present and live_present:status='BACKUP_AVAILABLE'
    elif backup_present and not live_present:status='RECOVERY_REQUIRED'
    else:status='CLEAN'
    return UpdateRecoveryState(status,backup_present,quarantine_present,live_present)

def recover_interrupted_update(config,backup_dir,recovery_stage):
    state=inspect_interrupted_update(config,backup_dir);live=Path(config.data_dir);stage=Path(recovery_stage)
    if state.status!='RECOVERY_REQUIRED':raise UpdateRollbackError(f'automatic recovery refused: {state.status}')
    if stage.exists():raise FileExistsError(f'recovery stage already exists: {stage}')
    restore(backup_dir,stage)
    if live.exists():raise UpdateRollbackError('live state appeared during recovery')
    stage.replace(live)
    return inspect_interrupted_update(config,backup_dir)


@dataclass(frozen=True)
class CutoverRecord:
    path:str; previous_authority:str; previous_endpoint:str; candidate_authority:str; candidate_endpoint:str; rollback_procedure:str; status:str; updated_at:float; switch_target:str=''; readback_target:str=''; generation:int=1; release_scope:dict|None=None; release_scope_ref:str=''; release_run_id:str=''; release_request_ref:str=''; release_canon_revision:str=''; rollback_readback_target:str=''

class CutoverRegistry:
    """Durable H4/H5 authority ledger. It records intent/state; it never switches a service itself."""
    _KNOWN=tuple(CutoverRecord.__dataclass_fields__)
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
    def _read(self):
        if not self.path.exists():return {}
        try: row=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,json.JSONDecodeError) as exc: raise UpdateRollbackError('cutover registry unreadable') from exc
        if row.get('schema') not in {1,2} or not isinstance(row.get('paths'),dict):raise UpdateRollbackError('cutover registry invalid')
        if row.get('schema')==1:
            return {k:{**v,'generation':1,'history':[{**v,'generation':1}]} for k,v in row['paths'].items()}
        return row['paths']
    def _write(self,paths):
        fd,tmp=tempfile.mkstemp(dir=self.path.parent,prefix='.cutover-',text=True)
        try:
            with os.fdopen(fd,'w') as f:json.dump({'schema':2,'paths':paths},f,indent=2);f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    def _rec(self,row): return CutoverRecord(**{k:row.get(k, CutoverRecord.__dataclass_fields__[k].default) for k in self._KNOWN if k!='history'})
    def prepare(self,path,previous_authority,previous_endpoint,candidate_authority,candidate_endpoint,rollback_procedure,switch_target='',readback_target='',*,verified_predecessor_ref=None,**extra):
        vals=(path,previous_authority,previous_endpoint,candidate_authority,candidate_endpoint,rollback_procedure,switch_target,readback_target)
        if any(not isinstance(x,str) or not x.strip() for x in vals):raise ValueError('complete cutover metadata required')
        rows=self._read(); prior=rows.get(path)
        if prior and prior.get('status')=='VERIFIED':
            # Advancing a successfully installed service MUST be a new
            # generation. The real owner host independently proves that the
            # predecessor is still the loaded, pinned runtime, then supplies
            # its exact previous release scope. A stale/ref-only model caller
            # cannot synthesize the separate Guard production approval.
            history=prior.get('history')
            if (type(verified_predecessor_ref) is not str
                    or not verified_predecessor_ref
                    or verified_predecessor_ref!=prior.get('release_scope_ref')
                    or extra.get('release_scope_ref') in (None,verified_predecessor_ref)
                    or previous_endpoint!=prior.get('candidate_endpoint')
                    or candidate_authority==prior.get('candidate_authority')
                    or type(history) is not list or not history
                    or history[-1].get('status')!='VERIFIED'
                    or history[-1].get('release_scope_ref')!=verified_predecessor_ref
                    or history[-1].get('generation')!=prior.get('generation')):
                raise ValueError('verified incumbent release readback required')
        elif prior and prior.get('status')!='ROLLED_BACK':
            raise ValueError('cutover already active')
        generation=(int(prior.get('generation',1))+1) if prior else 1
        meta={k:v for k,v in extra.items() if k in CutoverRecord.__dataclass_fields__}
        rec=CutoverRecord(path,previous_authority,previous_endpoint,candidate_authority,candidate_endpoint,rollback_procedure,'PREPARED',time.time(),switch_target,readback_target,generation,**meta)
        history=list(prior.get('history',[])) if prior else [];history.append(rec.__dict__.copy());rows[path]={**rec.__dict__,'history':history};self._write(rows);return rec
    def transition(self,path,expected,new_status):
        if new_status not in {'CUTOVER','ROLLED_BACK','VERIFIED'}:raise ValueError('invalid cutover status')
        rows=self._read();row=rows.get(path)
        if row is None or row.get('status')!=expected:raise UpdateRollbackError('cutover transition conflict')
        row={k:row.get(k, CutoverRecord.__dataclass_fields__[k].default) for k in self._KNOWN};row['status']=new_status;row['updated_at']=time.time()
        history=list(rows[path].get('history',[]));history.append({k:v for k,v in row.items()});row['history']=history;rows[path]=row;self._write(rows);return self._rec(row)
    def get(self,path):
        row=self._read().get(path);return self._rec(row) if row else None
    def history(self,path):
        row=self._read().get(path);return tuple(self._rec(x) for x in (row.get('history',[]) if row else []))
