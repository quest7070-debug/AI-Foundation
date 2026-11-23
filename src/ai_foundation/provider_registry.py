from dataclasses import dataclass
import sqlite3
import math,time
from pathlib import Path

def _valid_quota_remaining(value):
    """Strict finite percentage for both onboarding and live observations."""
    # Range-check before math.isfinite: huge Python integers otherwise
    # overflow during conversion to float, even though clearly outside 0..100.
    return (type(value) in (int, float)
            and 0 <= value <= 100
            and math.isfinite(value))


@dataclass(frozen=True)
class ProviderCard:
    provider:str; tier:str; credentials:int; health:str
    short_remaining:float|None=None; short_reset:str|None=None
    long_remaining:float|None=None; long_reset:str|None=None
    reason:str|None=None; updated_at:float|None=None

class SQLiteProviderRegistry:
    def __init__(self,path,storage_admission=None):
        self.path=Path(path); self.storage_admission=storage_admission; self.path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS provider_credentials(
              binding TEXT PRIMARY KEY, provider TEXT NOT NULL, tier TEXT NOT NULL,
              health TEXT NOT NULL, short_remaining REAL, short_reset TEXT,
              long_remaining REAL, long_reset TEXT, active INTEGER NOT NULL DEFAULT 0,
              reason TEXT, updated_at REAL NOT NULL, endpoint TEXT, model TEXT, auth_style TEXT, protocol TEXT, capabilities TEXT)""")
            cols={r[1] for r in db.execute('PRAGMA table_info(provider_credentials)')}
            for name in ('endpoint','model','auth_style','protocol','capabilities'):
                if name not in cols: db.execute(f'ALTER TABLE provider_credentials ADD COLUMN {name} TEXT')
    def _require_write(self,operation='provider registry'):
        if self.storage_admission:self.storage_admission.require(operation)
    def upsert(self,binding,provider,tier='FREE',health='ONLINE',short_remaining=None,short_reset=None,long_remaining=None,long_reset=None,active=False,reason=None,endpoint=None,model=None,auth_style=None,protocol=None,capabilities=()):
        self._require_write()
        if not binding or not provider: raise ValueError('binding and provider required')
        tier=tier.upper()
        if tier not in {'FREE','PAID'}: raise ValueError('tier must be FREE or PAID')
        if type(active) is not bool:
            raise ValueError('provider activity must be boolean')
        for q in (short_remaining,long_remaining):
            if q is not None and not _valid_quota_remaining(q):
                raise ValueError('quota remaining must be 0..100 percent')
        # Some providers authenticate successfully but do not expose comparable
        # machine-readable remaining quota. Preserve unknown as NULL; never fabricate it.
        import json
        vals=(binding,provider.upper(),tier,health.upper(),short_remaining,short_reset,long_remaining,long_reset,int(active),reason,time.time(),endpoint,model,auth_style,protocol,json.dumps(tuple(capabilities)))
        with sqlite3.connect(self.path) as db:
            db.execute("""INSERT INTO provider_credentials(binding,provider,tier,health,short_remaining,short_reset,long_remaining,long_reset,active,reason,updated_at,endpoint,model,auth_style,protocol,capabilities) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(binding) DO UPDATE SET provider=excluded.provider,tier=excluded.tier,health=excluded.health,
            short_remaining=excluded.short_remaining,short_reset=excluded.short_reset,long_remaining=excluded.long_remaining,
            long_reset=excluded.long_reset,active=excluded.active,reason=excluded.reason,updated_at=excluded.updated_at,endpoint=excluded.endpoint,model=excluded.model,auth_style=excluded.auth_style,protocol=excluded.protocol,capabilities=excluded.capabilities""",vals)
    def remove(self,binding):
        self._require_write()
        with sqlite3.connect(self.path) as db: db.execute('DELETE FROM provider_credentials WHERE binding=?',(binding,))
    def cards(self):
        with sqlite3.connect(self.path) as db:
            rows=db.execute("SELECT binding,provider,tier,health,short_remaining,short_reset,long_remaining,long_reset,active,reason,updated_at FROM provider_credentials ORDER BY provider,tier,binding").fetchall()
        groups={}
        for row in rows: groups.setdefault((row[1],row[2]),[]).append(row)
        out=[]
        for (provider,tier),items in groups.items():
            short=min((x for x in items if x[4] is not None),key=lambda x:x[4],default=None)
            long=min((x for x in items if x[6] is not None),key=lambda x:x[6],default=None)
            bad=next((x for x in items if x[3]!='ONLINE'),None)
            reason_row=bad or next((x for x in items if x[9]),None)
            out.append(ProviderCard(provider,tier,len(items),bad[3] if bad else 'ONLINE',short[4] if short else None,short[5] if short else None,long[6] if long else None,long[7] if long else None,reason_row[9] if reason_row else None,max(x[10] for x in items)))
        return tuple(out)

    def observe(self,binding,health=None,short_remaining=None,short_reset=None,long_remaining=None,long_reset=None,active=None,reason=None):
        self._require_write()
        # Live provider headers are untrusted observations. Validate updates
        # with the same percentage bounds as registration: malformed, NaN or
        # negative remaining quota must never enter the free-route ledger.
        for remaining in (short_remaining,long_remaining):
            if remaining is not None and not _valid_quota_remaining(remaining):
                raise ValueError('quota remaining must be 0..100 percent')
        if active is not None and type(active) is not bool:
            raise ValueError('provider activity observation must be boolean')
        fields=[]; vals=[]
        for name,value in (('health',health),('short_remaining',short_remaining),('short_reset',short_reset),('long_remaining',long_remaining),('long_reset',long_reset),('active',None if active is None else int(active)),('reason',reason)):
            if value is not None: fields.append(f'{name}=?'); vals.append(value)
        # A successful observation supersedes a prior failure reason. None normally means
        # 'leave unchanged', so ONLINE needs an explicit NULL write to avoid contradictory UI.
        if health=='ONLINE' and reason is None:
            fields.append('reason=?'); vals.append(None)
        if not fields: return False
        fields.append('updated_at=?'); vals.append(time.time()); vals.append(binding)
        with sqlite3.connect(self.path) as db:
            cur=db.execute(f"UPDATE provider_credentials SET {','.join(fields)} WHERE binding=?",vals)
            return cur.rowcount==1

    def set_execution_metadata(self,binding,*,endpoint,model,auth_style,protocol,capabilities):
        self._require_write()
        """Reconcile adapter-owned execution metadata without changing observed health/quota."""
        with sqlite3.connect(self.path) as db:
            cur=db.execute(
                'UPDATE provider_credentials SET endpoint=?,model=?,auth_style=?,protocol=?,capabilities=? WHERE binding=?',
                (endpoint,model,auth_style,protocol,__import__('json').dumps(tuple(capabilities)),binding),
            )
            if cur.rowcount!=1: raise KeyError(binding)

    def credential(self,binding):
        with sqlite3.connect(self.path) as db:
            row=db.execute('SELECT binding,provider,tier,health,short_remaining,short_reset,long_remaining,long_reset,active,reason,endpoint,model,auth_style,protocol,capabilities FROM provider_credentials WHERE binding=?',(binding,)).fetchone()
        if not row: return None
        return {'binding':row[0],'provider':row[1],'tier':row[2],'health':row[3],'short_remaining':row[4],'short_reset':row[5],'long_remaining':row[6],'long_reset':row[7],'active':bool(row[8]),'reason':row[9],'endpoint':row[10],'model':row[11],'auth_style':row[12],'protocol':row[13],'capabilities':tuple(__import__('json').loads(row[14] or '[]'))}

    def credentials(self):
        with sqlite3.connect(self.path) as db:
            rows=db.execute('SELECT binding,provider,tier,health,short_remaining,short_reset,long_remaining,long_reset,active,reason,updated_at,endpoint,model,auth_style,protocol,capabilities FROM provider_credentials ORDER BY binding').fetchall()
        return tuple({'binding':r[0],'provider':r[1],'tier':r[2],'health':r[3],'short_remaining':r[4],'short_reset':r[5],'long_remaining':r[6],'long_reset':r[7],'active':bool(r[8]),'reason':r[9],'updated_at':r[10],'endpoint':r[11],'model':r[12],'auth_style':r[13],'protocol':r[14],'capabilities':tuple(__import__('json').loads(r[15] or '[]'))} for r in rows)

    def bindings(self):
        with sqlite3.connect(self.path) as db:
            return tuple(r[0] for r in db.execute('SELECT binding FROM provider_credentials ORDER BY binding'))

    def integrity_check(self):
        try:
            with sqlite3.connect(self.path) as db:
                result=db.execute('PRAGMA integrity_check').fetchone()
                required={'binding','provider','tier','health','updated_at'}
                cols={r[1] for r in db.execute('PRAGMA table_info(provider_credentials)')}
            return {'ok':bool(result and result[0]=='ok' and required<=cols),'sqlite':result[0] if result else 'no result','schema':required<=cols}
        except sqlite3.DatabaseError as exc:
            return {'ok':False,'sqlite':'corrupt','schema':False,'reason':type(exc).__name__}
