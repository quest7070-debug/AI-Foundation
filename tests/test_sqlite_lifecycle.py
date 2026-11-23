import sqlite3
from ai_foundation.sqlite_lifecycle import inspect,passive_checkpoint

def test_churn_reuses_pages_and_integrity_survives(tmp_path):
 p=tmp_path/'x.db'
 with sqlite3.connect(p) as d:
  d.execute('pragma journal_mode=wal');d.execute('create table x(id integer primary key,v text)');d.executemany('insert into x(v) values(?)',[('x'*500,) for _ in range(3000)])
 first=inspect(p);assert first.quick_check=='ok'
 with sqlite3.connect(p) as d:d.execute('delete from x where id<=2000')
 freed=inspect(p);assert freed.freelist_count>0
 with sqlite3.connect(p) as d:d.executemany('insert into x(v) values(?)',[('y'*500,) for _ in range(1500)])
 reused=inspect(p);assert reused.quick_check=='ok' and reused.freelist_count<freed.freelist_count
 assert reused.page_count<=freed.page_count+50

def test_passive_checkpoint_preserves_integrity(tmp_path):
 p=tmp_path/'x.db';writer=sqlite3.connect(p);writer.execute('pragma journal_mode=wal');writer.execute('create table x(v)');writer.executemany('insert into x values(?)',[(str(i),) for i in range(2000)]);writer.commit()
 before=inspect(p);assert before.wal_bytes>0
 result=passive_checkpoint(p);assert len(result)==3 and inspect(p).quick_check=='ok'
 writer.close()

def test_wal_checkpoint_with_active_reader_and_writer_is_non_destructive(tmp_path):
 p=tmp_path/'x.db';writer=sqlite3.connect(p);writer.execute('pragma journal_mode=wal');writer.execute('create table x(id integer primary key,v text)');writer.executemany('insert into x(v) values(?)',[(str(i),) for i in range(1000)]);writer.commit()
 reader=sqlite3.connect(p);reader.execute('begin');assert reader.execute('select count(*) from x').fetchone()[0]==1000
 writer.executemany('insert into x(v) values(?)',[(f'n{i}',) for i in range(1000)]);writer.commit()
 before=inspect(p);result=passive_checkpoint(p);after=inspect(p)
 assert result[0] in (0,1) and after.quick_check=='ok' and reader.execute('select count(*) from x').fetchone()[0]==1000
 reader.rollback();reader.close();writer.close()
 with sqlite3.connect(p) as d:assert d.execute('select count(*) from x').fetchone()[0]==2000

def test_repeated_churn_file_growth_reaches_reuse_plateau(tmp_path):
 p=tmp_path/'x.db'
 with sqlite3.connect(p) as d:d.execute('pragma journal_mode=wal');d.execute('create table x(id integer primary key,v text)')
 sizes=[]
 for cycle in range(12):
  with sqlite3.connect(p) as d:
   d.executemany('insert into x(v) values(?)',[('x'*700,) for _ in range(1200)])
   d.execute('delete from x where id in (select id from x order by id limit 1200)')
  passive_checkpoint(p);sizes.append(inspect(p).page_count)
 assert max(sizes[-5:])-min(sizes[-5:])<=3
 assert inspect(p).quick_check=='ok'

def test_subprocess_crash_recovers_committed_and_discards_uncommitted(tmp_path):
 import subprocess,sys
 p=tmp_path/'crash.db';probe='scripts/sqlite_crash_probe.py'
 assert subprocess.run([sys.executable,probe,str(p),'committed']).returncode==73
 assert inspect(p).quick_check=='ok'
 with sqlite3.connect(p) as d:assert d.execute("select count(*) from x where v='committed'").fetchone()[0]==1
 assert subprocess.run([sys.executable,probe,str(p),'uncommitted']).returncode==73
 assert inspect(p).quick_check=='ok'
 with sqlite3.connect(p) as d:
  assert d.execute("select count(*) from x where v='committed'").fetchone()[0]==1
  assert d.execute("select count(*) from x where v='uncommitted'").fetchone()[0]==0
