"""Durable local-index evidence; no semantic authority or provider permission."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

SCHEMA = 'foundation-infigraph-receipt/v1'
MAX_INDEX_BYTES = 512 * 1024 * 1024
MAX_INDEX_FILES = 20000
MAX_RECEIPT_BYTES = 4 * 1024 * 1024


def _regular(path):
    info=path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid not in (os.getuid(),0)
            or info.st_mode & 0o022 or path.resolve(strict=True)!=path):
        raise ValueError('untrusted index evidence file')
    return info


def _hash(path):
    before=_regular(path)
    digest=hashlib.sha256()
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:
        opened=os.fstat(stream.fileno())
        if (opened.st_dev,opened.st_ino)!=(before.st_dev,before.st_ino):
            raise ValueError('index evidence identity changed during open')
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    after=_regular(path)
    if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(
            after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):
        raise ValueError('index evidence changed during read')
    return digest.hexdigest()


class InfigraphIndexReceipt:
    def __init__(self, *, root: Path, executable: Path, receipt: Path):
        self.root=Path(root).resolve(strict=True)
        self.executable=Path(os.path.abspath(os.fspath(executable)))
        self.receipt=Path(receipt)
        if (not self.receipt.is_absolute() or self.receipt.is_relative_to(self.root)
                or '..' in self.receipt.parts):
            raise ValueError('index receipt must be outside the worktree')

    def _directory(self, *, create=False):
        parent=self.receipt.parent
        if create:parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        info=parent.lstat()
        if (parent.resolve(strict=True)!=parent or not stat.S_ISDIR(info.st_mode)
                or info.st_uid!=os.getuid() or info.st_mode & 0o077):
            raise ValueError('private index receipt directory required')
        return parent

    @contextmanager
    def read_lock(self):
        self._directory(create=True)
        lock=self.receipt.with_suffix(self.receipt.suffix+'.lock')
        fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid()
                    or info.st_mode & 0o077 or info.st_nlink!=1):
                raise ValueError('untrusted index refresh lock')
            fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
            yield
        finally:os.close(fd)

    @contextmanager
    def refresh_lock(self):
        self._directory(create=True)
        lock=self.receipt.with_suffix(self.receipt.suffix+'.lock')
        fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid()
                    or info.st_mode & 0o077 or info.st_nlink!=1):
                raise ValueError('untrusted index refresh lock')
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            yield
        finally:os.close(fd)

    def executable_identity(self):
        return _hash(self.executable)

    def invalidate(self):
        self._directory()
        try:
            _regular(self.receipt)
        except FileNotFoundError:
            return
        self.receipt.unlink()
        fd=os.open(self.receipt.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)

    def snapshot(self):
        index=self.root/'.infigraph'
        info=index.lstat()
        if (not stat.S_ISDIR(info.st_mode) or index.resolve(strict=True)!=index
                or info.st_uid!=os.getuid() or info.st_mode & 0o022):
            raise ValueError('owned local index directory required')
        paths=[]
        for path in index.rglob('*'):
            if len(paths)>=MAX_INDEX_FILES:raise ValueError('index inventory exceeds bound')
            paths.append(path)
        paths.sort()
        result={};total=0
        for path in paths:
            info=path.lstat()
            if stat.S_ISDIR(info.st_mode):
                if info.st_uid!=os.getuid() or info.st_mode & 0o022:
                    raise ValueError('untrusted index directory')
                continue
            info=_regular(path);total+=info.st_size
            if total>MAX_INDEX_BYTES:raise ValueError('index bytes exceed bound')
            result[str(path.relative_to(index))]=_hash(path)
        if not result:raise ValueError('local index has no persisted artifacts')
        remaining=set(paths)
        for path in index.rglob('*'):
            if path not in remaining:raise ValueError('index inventory changed during read')
            remaining.remove(path)
        if remaining:raise ValueError('index inventory changed during read')
        return result

    def _binding(self, source,version):
        info=self.root.stat()
        return {'schema':SCHEMA,'root':str(self.root),'device':info.st_dev,'inode':info.st_ino,
            'sourceRevision':source,'backendVersion':version,'executable':str(self.executable),
            'executableSha256':_hash(self.executable),'artifacts':self.snapshot()}

    def commit(self, source,version):
        parent=self._directory()
        value=self._binding(source,version)
        # Flush the local artifacts before publishing a receipt for their bytes.
        for relative in value['artifacts']:
            path=self.root/'.infigraph'/relative
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
            try:os.fsync(fd)
            finally:os.close(fd)
        for directory in [p for p in (self.root/'.infigraph').rglob('*') if p.is_dir()] + [self.root/'.infigraph', self.root]:
            fd=os.open(directory,os.O_RDONLY|os.O_NOFOLLOW)
            try:os.fsync(fd)
            finally:os.close(fd)
        payload=json.dumps(value,sort_keys=True,separators=(',', ':')).encode()
        if len(payload)>MAX_RECEIPT_BYTES:raise ValueError('index receipt exceeds bound')
        fd,name=tempfile.mkstemp(prefix='.index-receipt-',dir=parent)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(payload);stream.flush();os.fsync(stream.fileno())
            os.replace(name,self.receipt)
            fd=os.open(parent,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
        finally:
            if os.path.exists(name):os.unlink(name)
        self.verify(source,version)

    def verify(self,source,version):
        self._directory()
        info=_regular(self.receipt)
        if info.st_uid!=os.getuid() or info.st_mode & 0o077 or info.st_size>MAX_RECEIPT_BYTES:
            raise ValueError('invalid private index receipt')
        fd=os.open(self.receipt,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as stream:raw=stream.read(MAX_RECEIPT_BYTES+1)
        expected=self._binding(source,version)
        if raw!=json.dumps(expected,sort_keys=True,separators=(',', ':')).encode():
            raise ValueError('persisted index receipt no longer matches')
        return source
