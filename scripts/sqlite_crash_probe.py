#!/usr/bin/env python3
"""Disposable subprocess used only to prove WAL crash recovery."""
import sqlite3,sys,os
p=sys.argv[1];mode=sys.argv[2]
d=sqlite3.connect(p);d.execute('pragma journal_mode=wal');d.execute('create table if not exists x(id integer primary key,v text)')
if mode=='committed':d.execute("insert into x(v) values('committed')");d.commit()
elif mode=='uncommitted':d.execute('begin immediate');d.execute("insert into x(v) values('uncommitted')")
os._exit(73)
