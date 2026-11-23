"""Owner-scoped attachment handoff. LibreChat IDs are resolved by trusted host code before Foundation sees paths."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os,time,threading,uuid
from functools import wraps
from .filesystem_lock import exclusive_file_lock
from .capability_request import AttachmentGrant


def _is_within(path,root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

def _serialized_lifecycle(method):
    @wraps(method)
    def locked(self, *args, **kwargs):
        if not self.handoff_root.exists():
            return ()
        with exclusive_file_lock(self.root / '.foundation-handoff.lock'):
            return method(self, *args, **kwargs)
    return locked


@dataclass(frozen=True)
class AttachmentRecord:
    attachment_id:str
    owner_id:str
    path:str = ""
    text:str|None = None

class AttachmentHandoff:
    def __init__(self,root,lookup,storage_admission=None,*,trusted_roots=None):
        self.root=Path(root).resolve()
        self.lookup=lookup
        self.storage_admission=storage_admission
        roots=(self.root,) if trusted_roots is None else tuple(Path(x).resolve() for x in trusted_roots)
        if not roots:
            raise ValueError("trusted attachment roots required")
        self.trusted_roots=tuple(dict.fromkeys(roots))
        self._leases = {}

    @property
    def handoff_root(self): return self.root/'.foundation-handoff'

    def acquire(self,grant):
        """Acquire one reader lease; each matching release retires only that use."""
        path=Path(grant.path).resolve()
        try:path.relative_to(self.handoff_root.resolve())
        except ValueError:return False
        with exclusive_file_lock(self.root / '.foundation-handoff.lock'):
            if not path.is_file():
                raise FileNotFoundError('materialized attachment no longer available')
            # Keep the legacy name for the first reader; overlapping readers use
            # distinct markers, including across separate host processes.
            lease=path.with_suffix(path.suffix+'.lease')
            while True:
                try:
                    fd=os.open(lease,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                    break
                except FileExistsError:
                    lease=path.with_name(path.name+'.'+uuid.uuid4().hex+'.lease')
            try:
                with os.fdopen(fd,'w') as stream:
                    stream.write(f'{os.getpid()}\n{time.time_ns()}\n')
                    stream.flush();os.fsync(stream.fileno())
            except BaseException:
                lease.unlink(missing_ok=True)
                raise
            key=(os.getpid(),threading.get_ident(),str(path))
            self._leases.setdefault(key,[]).append(lease)
        return True

    def release(self,grant):
        path=Path(grant.path).resolve()
        key=(os.getpid(),threading.get_ident(),str(path))
        # An unmatched release must never remove another request's lease.
        with exclusive_file_lock(self.root / '.foundation-handoff.lock'):
            leases=self._leases.get(key)
            if not leases:return
            leases.pop().unlink(missing_ok=True)
            if not leases:del self._leases[key]

    @staticmethod
    def _leased_names(handoff):
        # One scan per maintenance pass; globbing once per content file would
        # make the large-fanout cleanup quadratic.
        names=set()
        for lease in handoff.glob('*.lease'):
            base=lease.name[:-len('.lease')]
            names.add(base)
            if '.txt.' in base:
                names.add(base.split('.txt.',1)[0]+'.txt')
        return names

    @staticmethod
    def _pid_alive(pid):
        try:os.kill(pid,0); return True
        except ProcessLookupError:return False
        except PermissionError:return True

    @_serialized_lifecycle
    def recover_stale_leases(self,*,pid_alive=None):
        """Remove leases whose recorded process no longer exists; malformed leases fail closed."""
        alive=pid_alive or self._pid_alive; removed=[]; handoff=self.handoff_root
        if not handoff.exists(): return tuple()
        for tmp in handoff.glob('*.tmp'):
            try:tmp.unlink(); removed.append(tmp.name)
            except (FileNotFoundError,OSError):pass
        for lease in handoff.glob('*.lease'):
            try:
                lines=lease.read_text(encoding='ascii').splitlines()
                if not lines: continue
                pid=int(lines[0])
                if alive(pid): continue
                lease.unlink(); removed.append(lease.name)
            except (OSError,ValueError,UnicodeError): continue
        return tuple(removed)

    @_serialized_lifecycle
    def cleanup(self,*,max_age_seconds=24*3600,now=None):
        """Remove only old inactive host-materialized handoff files; never source uploads."""
        cutoff=(time.time() if now is None else now)-max_age_seconds
        removed=[]
        handoff=self.handoff_root
        if not handoff.exists(): return tuple()
        leased=self._leased_names(handoff)
        for entry in handoff.iterdir():
            try:
                if entry.is_symlink() or not entry.is_file() or entry.name.endswith(('.lease','.meta')): continue
                if entry.stat().st_mtime >= cutoff: continue
                if entry.name in leased: continue
                entry.unlink(); removed.append(entry.name)
                try:entry.with_suffix('.meta').unlink()
                except FileNotFoundError:pass
            except FileNotFoundError: pass
        return tuple(removed)

    @_serialized_lifecycle
    def reconcile_upstream(self):
        """Remove inactive derived copies whose owner-scoped upstream record no longer exists."""
        removed=[];handoff=self.handoff_root
        if not handoff.exists():return tuple()
        leased=self._leased_names(handoff)
        for meta in handoff.glob('*.meta'):
            path=meta.with_suffix('.txt')
            if path.name in leased:continue
            try:
                owner,attachment_id=meta.read_text(encoding='utf-8').splitlines()[:2]
                try:rec=self.lookup(attachment_id,owner)
                except TypeError:rec=self.lookup(attachment_id)
                if rec is not None:continue
                if path.exists():path.unlink();removed.append(path.name)
                meta.unlink()
            except (OSError,ValueError,IndexError,UnicodeError):continue
        return tuple(removed)

    def resolve(self,owner_id:str,attachment_ids):
        if not owner_id: raise ValueError("attachment owner required")
        grants=[]
        seen=set()
        for attachment_id in attachment_ids:
            if not isinstance(attachment_id,str) or not attachment_id or attachment_id in seen:
                raise ValueError("invalid attachment id")
            seen.add(attachment_id)
            try: rec=self.lookup(attachment_id,owner_id)
            except TypeError: rec=self.lookup(attachment_id)
            if rec is None: raise FileNotFoundError(attachment_id)
            if rec.owner_id != owner_id: raise PermissionError("attachment owner mismatch")
            if rec.text is not None:
                if self.storage_admission:self.storage_admission.require('attachment materialization')
                path=self._materialize(rec)
            else:
                raw_path=Path(rec.path)
                if raw_path.is_symlink(): raise PermissionError("attachment symlink rejected")
                path=raw_path.resolve()
            if not any(_is_within(path,root) for root in self.trusted_roots):
                raise PermissionError("attachment outside trusted attachment roots")
            if not path.is_file(): raise FileNotFoundError(attachment_id)
            grants.append(AttachmentGrant(rec.attachment_id,rec.owner_id,str(path)))
        return tuple(grants)

    def _materialize(self,rec):
        import hashlib
        handoff=self.handoff_root
        handoff.mkdir(mode=0o700,exist_ok=True)
        with exclusive_file_lock(self.root / '.foundation-handoff.lock'):
            identity=hashlib.sha256((rec.owner_id+'\0'+rec.attachment_id).encode()).hexdigest()
            content=hashlib.sha256(rec.text.encode('utf-8')).hexdigest()
            # An updated upstream record cannot overwrite a snapshot in use.
            name=identity+'-'+content+'.txt'
            path=(handoff/name).resolve()
            meta=path.with_suffix('.meta')
            tmp=handoff/(name+'.tmp')
            meta_tmp=meta.with_suffix('.meta.tmp')
            try:
                tmp.write_text(rec.text,encoding='utf-8');tmp.chmod(0o600)
                meta_tmp.write_text(rec.owner_id+'\n'+rec.attachment_id+'\n',encoding='utf-8');meta_tmp.chmod(0o600)
                os.replace(tmp,path);path.chmod(0o600)
                os.replace(meta_tmp,meta)
            except Exception:
                for partial in (tmp,meta_tmp):
                    partial.unlink(missing_ok=True)
                raise
            return path

class AttachmentCleanupLoop:
    """Periodic mutation loop kept separate from observation/health."""
    def __init__(self,handoff,*,max_age_seconds=24*3600,interval=3600):
        import threading
        self.handoff=handoff; self.max_age_seconds=max_age_seconds; self.interval=max(60,interval)
        self._stop=threading.Event(); self._last_removed=()
    def tick(self):
        self.handoff.recover_stale_leases()
        upstream=self.handoff.reconcile_upstream()
        expired=self.handoff.cleanup(max_age_seconds=self.max_age_seconds)
        self._last_removed=upstream+expired
        return self._last_removed
    def run(self):
        self.tick()
        while not self._stop.wait(self.interval):self.tick()
    def start(self):
        import threading
        t=threading.Thread(target=self.run,name='foundation-attachment-cleanup',daemon=True);t.start();return t
    def stop(self):self._stop.set()

