"""Owner-neutral SQLite lifecycle observation and safe maintenance primitives."""
from dataclasses import dataclass
from pathlib import Path
import sqlite3

@dataclass(frozen=True)
class SQLiteLifecycleStatus:
 path:str; journal_mode:str; page_size:int; page_count:int; freelist_count:int; wal_bytes:int; quick_check:str
 @property
 def reusable_bytes(self):return self.page_size*self.freelist_count

def inspect(path):
 p=Path(path)
 with sqlite3.connect(f'file:{p}?mode=ro',uri=True) as db:
  one=lambda q:db.execute(q).fetchone()[0]
  return SQLiteLifecycleStatus(str(p),str(one('PRAGMA journal_mode')),int(one('PRAGMA page_size')),int(one('PRAGMA page_count')),int(one('PRAGMA freelist_count')),(p.parent/(p.name+'-wal')).stat().st_size if (p.parent/(p.name+'-wal')).exists() else 0,str(one('PRAGMA quick_check')))

def passive_checkpoint(path):
 """Request SQLite's own passive WAL checkpoint; never VACUUM or rewrite pages."""
 with sqlite3.connect(path,timeout=5) as db:
  return tuple(db.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone())
