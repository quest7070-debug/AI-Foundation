import sqlite3
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from .core import EffectIntent, EffectStatus, GuardState

def approval_request_ref(run_id, action, target, nonce, canon_revision="", effect_id=""):
    """Opaque binding for the exact pending Guard request, not an authority token."""
    raw = json.dumps([run_id, action, target, nonce, canon_revision, effect_id], ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()


_ALLOWED_TRANSITIONS = {
    EffectStatus.PLANNED: {EffectStatus.PLANNED, EffectStatus.AUTHORIZED},
    EffectStatus.AUTHORIZED: {EffectStatus.AUTHORIZED, EffectStatus.EXECUTING},
    EffectStatus.EXECUTING: {EffectStatus.EXECUTING, EffectStatus.UNCERTAIN, EffectStatus.OBSERVED, EffectStatus.VERIFIED},
    EffectStatus.UNCERTAIN: {EffectStatus.UNCERTAIN, EffectStatus.OBSERVED, EffectStatus.VERIFIED},
    EffectStatus.OBSERVED: {EffectStatus.OBSERVED, EffectStatus.VERIFIED, EffectStatus.FAILED},
    EffectStatus.VERIFIED: {EffectStatus.VERIFIED},
    EffectStatus.FAILED: {EffectStatus.FAILED},
}
class SQLiteGuardStore:
    def __init__(self, path: str | Path, storage_admission=None): self.path=str(path); self.storage_admission=storage_admission; self._init_db()
    def _connect(self):
        db=sqlite3.connect(self.path); db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA busy_timeout=5000'); return db
    def _init_db(self):
        with self._connect() as db: db.executescript("""
        CREATE TABLE IF NOT EXISTS approvals (run_id TEXT PRIMARY KEY, action TEXT NOT NULL DEFAULT '', target TEXT NOT NULL DEFAULT '', canon_revision TEXT NOT NULL DEFAULT '', effect_id TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS approval_requests (run_id TEXT PRIMARY KEY, action TEXT NOT NULL, target TEXT NOT NULL, updated_at REAL NOT NULL, request_nonce TEXT NOT NULL DEFAULT '', canon_revision TEXT NOT NULL DEFAULT '', effect_id TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS cancellations (run_id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS effects (effect_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, target TEXT NOT NULL, expected TEXT NOT NULL, status TEXT NOT NULL, paid_cost INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS guard_meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS effect_claims (effect_id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS budget_reservations (run_id TEXT PRIMARY KEY, amount INTEGER NOT NULL, created REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS target_claims (target TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS startup_leases (name TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL);
        INSERT OR IGNORE INTO guard_meta(key,value) VALUES ('spent',0);
        CREATE INDEX IF NOT EXISTS idx_effects_run_id ON effects(run_id);
        CREATE INDEX IF NOT EXISTS idx_approval_requests_updated ON approval_requests(updated_at DESC,run_id);
        CREATE INDEX IF NOT EXISTS idx_effect_claims_expires ON effect_claims(expires);
        CREATE INDEX IF NOT EXISTS idx_target_claims_expires ON target_claims(expires);
        CREATE INDEX IF NOT EXISTS idx_startup_leases_expires ON startup_leases(expires);
        CREATE INDEX IF NOT EXISTS idx_budget_reservations_created ON budget_reservations(created);""")
        with self._connect() as db:
            cols={r[1] for r in db.execute('PRAGMA table_info(effects)')}
            if 'updated_at' not in cols: db.execute('ALTER TABLE effects ADD COLUMN updated_at REAL NOT NULL DEFAULT 0')
            db.execute('CREATE INDEX IF NOT EXISTS idx_effects_status_updated ON effects(status,updated_at DESC,effect_id)')
            request_cols = {r[1] for r in db.execute('PRAGMA table_info(approval_requests)')}
            if 'request_nonce' not in request_cols:
                db.execute("ALTER TABLE approval_requests ADD COLUMN request_nonce TEXT NOT NULL DEFAULT ''")
            for col in ('canon_revision', 'effect_id'):
                if col not in request_cols:
                    db.execute(f"ALTER TABLE approval_requests ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
            approved_cols = {r[1] for r in db.execute('PRAGMA table_info(approvals)')}
            # Legacy run-only approvals remain historical, not authority
            # for a new plan with different action/target/Canon/effect.
            for col in ('action', 'target', 'canon_revision', 'effect_id'):
                if col not in approved_cols:
                    db.execute(f"ALTER TABLE approvals ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
            # Backfill once for preexisting pending requests without reopening them.
            db.execute("UPDATE approval_requests SET request_nonce=lower(hex(randomblob(16))) WHERE request_nonce=''")
    def _require_write(self,operation='guard write'):
        if self.storage_admission:self.storage_admission.require(operation)
    def request_approval(self,run_id,action,target,canon_revision='',effect_id=''):
        self._require_write('approval request')
        # A preflight may race with a human decision. Check the consumed run
        # while holding SQLite's write lock: otherwise a concurrent preflight
        # can resurrect a pending request after AUTHORIZE or DENY commits.
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            consumed = (
                db.execute('SELECT 1 FROM approvals WHERE run_id=?',(run_id,)).fetchone()
                or db.execute('SELECT 1 FROM cancellations WHERE run_id=?',(run_id,)).fetchone()
                or db.execute("SELECT 1 FROM effects WHERE run_id=? AND status!='PLANNED'",(run_id,)).fetchone()
            )
            if consumed:
                # Reconcile old stranded pending rows without granting authority.
                db.execute('DELETE FROM approval_requests WHERE run_id=?',(run_id,))
                return False
            # An identical current plan retains its nonce; any change rotates
            # it. Legacy unbound rows become actionable only after preflight
            # supplies both Canon and effect identity.
            db.execute(
                """INSERT INTO approval_requests(run_id,action,target,updated_at,request_nonce,canon_revision,effect_id)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(run_id) DO UPDATE SET
                       action=excluded.action,target=excluded.target,
                       updated_at=excluded.updated_at,request_nonce=excluded.request_nonce,
                       canon_revision=excluded.canon_revision,effect_id=excluded.effect_id
                   WHERE approval_requests.action!=excluded.action
                      OR approval_requests.target!=excluded.target
                      OR approval_requests.canon_revision!=excluded.canon_revision
                      OR approval_requests.effect_id!=excluded.effect_id""",
                (run_id,action,target,time.time(),secrets.token_hex(16),canon_revision,effect_id))
            return True
    def approve_pending(self,run_id,expected_ref):
        """Atomically authorize only a currently pending, unchanged request."""
        self._require_write('approve pending request')
        if not isinstance(expected_ref,str) or len(expected_ref)!=64:
            return False
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT action,target,request_nonce,canon_revision,effect_id FROM approval_requests WHERE run_id=?',(run_id,)).fetchone()
            # Migrated legacy requests do not identify a Canon/effect plan.
            # A nonce alone is not authorization: await a real Guard preflight.
            if row is None or not row[3] or not row[4] or not hmac.compare_digest(
                    approval_request_ref(run_id,*row),expected_ref):
                return False
            if db.execute('SELECT 1 FROM cancellations WHERE run_id=?',(run_id,)).fetchone():
                return False
            # A prior approved run cannot be silently retargeted; a changed
            # effect needs a fresh run and a fresh independent decision.
            if db.execute('SELECT 1 FROM approvals WHERE run_id=?',(run_id,)).fetchone():
                return False
            if db.execute("SELECT 1 FROM effects WHERE run_id=? AND status!='PLANNED'",(run_id,)).fetchone():
                return False
            db.execute(
                'INSERT INTO approvals(run_id,action,target,canon_revision,effect_id) VALUES(?,?,?,?,?)',
                (run_id,row[0],row[1],row[3],row[4]))
            db.execute('DELETE FROM approval_requests WHERE run_id=?',(run_id,))
            return True
    def has_pending(self,run_id):
        with self._connect() as db:
            return db.execute('SELECT 1 FROM approval_requests WHERE run_id=?',(run_id,)).fetchone() is not None

    def cancel_pending(self,run_id,expected_ref):
        """One-time, revision-bound denial of the exact pending Guard request."""
        self._require_write('cancel pending request')
        if not isinstance(expected_ref,str) or len(expected_ref)!=64:
            return False
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT action,target,request_nonce,canon_revision,effect_id FROM approval_requests WHERE run_id=?',(run_id,)).fetchone()
            # Migrated legacy requests do not identify a Canon/effect plan.
            # A nonce alone is not authorization: await a real Guard preflight.
            if row is None or not row[3] or not row[4] or not hmac.compare_digest(
                    approval_request_ref(run_id,*row),expected_ref):
                return False
            if db.execute('SELECT 1 FROM approvals WHERE run_id=?',(run_id,)).fetchone():
                return False
            db.execute('INSERT OR IGNORE INTO cancellations(run_id) VALUES(?)',(run_id,))
            db.execute('DELETE FROM approval_requests WHERE run_id=?',(run_id,))
            return True

    def resolve_approval(self,run_id):
        with self._connect() as db:db.execute('DELETE FROM approval_requests WHERE run_id=?',(run_id,))
    def runtime_state(self):
        """Bounded startup state: historical authority stays in SQLite and is read by key."""
        with self._connect() as db:
            spent=db.execute("SELECT value FROM guard_meta WHERE key='spent'").fetchone()[0]
        return GuardState(spent=spent)
    def is_approved(self,run_id):
        with self._connect() as db:return db.execute('SELECT 1 FROM approvals WHERE run_id=?',(run_id,)).fetchone() is not None
    def is_approved_for(self,run_id,action,target,canon_revision,effect_id):
        """Critical approval is bound to the exact persistent Guard plan."""
        with self._connect() as db:
            return db.execute(
                'SELECT 1 FROM approvals WHERE run_id=? AND action=? AND target=? '
                'AND canon_revision=? AND effect_id=?',
                (run_id,action,target,canon_revision,effect_id)
            ).fetchone() is not None

    def is_cancelled(self,run_id):
        with self._connect() as db:return db.execute('SELECT 1 FROM cancellations WHERE run_id=?',(run_id,)).fetchone() is not None
    def get_effect(self,effect_id):
        with self._connect() as db:r=db.execute('SELECT effect_id,run_id,target,expected,status,paid_cost FROM effects WHERE effect_id=?',(effect_id,)).fetchone()
        return EffectIntent(r[0],r[1],r[2],r[3],EffectStatus(r[4]),r[5]) if r else None
    def spent(self):
        with self._connect() as db:return db.execute("SELECT value FROM guard_meta WHERE key='spent'").fetchone()[0]

    def load(self):
        with self._connect() as db:
            approvals={r[0] for r in db.execute('SELECT run_id FROM approvals')}
            cancellations={r[0] for r in db.execute('SELECT run_id FROM cancellations')}
            effects={r[0]:EffectIntent(r[0],r[1],r[2],r[3],EffectStatus(r[4]),r[5]) for r in db.execute('SELECT effect_id,run_id,target,expected,status,paid_cost FROM effects')}
            spent=db.execute("SELECT value FROM guard_meta WHERE key='spent'").fetchone()[0]
        return GuardState(approvals,effects,spent,cancellations)
    def save(self,state):
        self._require_write('guard state')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.executemany('INSERT OR IGNORE INTO approvals(run_id) VALUES (?)',[(x,) for x in state.approvals])
            db.executemany('INSERT OR IGNORE INTO cancellations(run_id) VALUES (?)',[(x,) for x in state.cancellations])
            for e in state.effects.values():
                old=db.execute('SELECT status FROM effects WHERE effect_id=?',(e.effect_id,)).fetchone()
                old_status = EffectStatus(old[0]) if old else None
                was_verified = old_status is EffectStatus.VERIFIED
                if old_status is not None and e.status not in _ALLOWED_TRANSITIONS[old_status]:
                    continue
                db.execute('INSERT INTO effects(effect_id,run_id,target,expected,status,paid_cost,updated_at) VALUES (?,?,?,?,?,?,unixepoch()) ON CONFLICT(effect_id) DO UPDATE SET run_id=excluded.run_id,target=excluded.target,expected=excluded.expected,status=excluded.status,paid_cost=excluded.paid_cost,updated_at=CASE WHEN effects.status<>excluded.status THEN unixepoch() ELSE effects.updated_at END',(e.effect_id,e.run_id,e.target,e.expected,e.status.value,e.paid_cost))
                if e.status is EffectStatus.VERIFIED and not was_verified:
                    db.execute("UPDATE guard_meta SET value=value+? WHERE key='spent'",(e.paid_cost,))
                    db.execute('DELETE FROM budget_reservations WHERE run_id=?',(e.run_id,))
            state.spent=db.execute("SELECT value FROM guard_meta WHERE key='spent'").fetchone()[0]

    def transition_effect(self, effect_id, expected_status, new_status):
        self._require_write('effect transition')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT status,paid_cost,run_id FROM effects WHERE effect_id=?',(effect_id,)).fetchone()
            if not row or EffectStatus(row[0]) is not expected_status or new_status not in _ALLOWED_TRANSITIONS[expected_status]:
                return False
            cur=db.execute('UPDATE effects SET status=?,updated_at=unixepoch() WHERE effect_id=? AND status=?',(new_status.value,effect_id,expected_status.value))
            if cur.rowcount != 1: return False
            if new_status is EffectStatus.VERIFIED:
                db.execute("UPDATE guard_meta SET value=value+? WHERE key='spent'",(row[1],))
                db.execute('DELETE FROM budget_reservations WHERE run_id=?',(row[2],))
            return True

    def claim_for_reconcile(self, effect_id, owner, now, ttl=30.0):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT status FROM effects WHERE effect_id=?',(effect_id,)).fetchone()
            if not row or EffectStatus(row[0]) not in {EffectStatus.EXECUTING,EffectStatus.UNCERTAIN,EffectStatus.OBSERVED}: return False
            claim=db.execute('SELECT owner,expires FROM effect_claims WHERE effect_id=?',(effect_id,)).fetchone()
            if claim and claim[1] > now and claim[0] != owner: return False
            db.execute('INSERT INTO effect_claims(effect_id,owner,expires) VALUES (?,?,?) ON CONFLICT(effect_id) DO UPDATE SET owner=excluded.owner,expires=excluded.expires',(effect_id,owner,now+ttl))
            return True

    def try_claim(self, effect_id, owner, now, ttl=30.0):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT owner,expires FROM effect_claims WHERE effect_id=?',(effect_id,)).fetchone()
            if row and row[1] > now and row[0] != owner: return False
            db.execute('INSERT INTO effect_claims(effect_id,owner,expires) VALUES (?,?,?) ON CONFLICT(effect_id) DO UPDATE SET owner=excluded.owner,expires=excluded.expires',(effect_id,owner,now+ttl))
            return True
    def renew_claim(self, effect_id, owner, now, ttl=30.0):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            cur=db.execute('UPDATE effect_claims SET expires=? WHERE effect_id=? AND owner=? AND expires>?',(now+ttl,effect_id,owner,now))
            return cur.rowcount == 1
    def claim_owner(self, effect_id, now):
        with self._connect() as db:
            row=db.execute('SELECT owner,expires FROM effect_claims WHERE effect_id=?',(effect_id,)).fetchone()
            return row[0] if row and row[1] > now else None
    def release_claim(self, effect_id, owner):
        with self._connect() as db: db.execute('DELETE FROM effect_claims WHERE effect_id=? AND owner=?',(effect_id,owner))

    def try_claim_target(self, target, owner, now, ttl=30.0):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT owner,expires FROM target_claims WHERE target=?',(target,)).fetchone()
            if row and row[1] > now and row[0] != owner: return False
            db.execute('INSERT INTO target_claims(target,owner,expires) VALUES (?,?,?) ON CONFLICT(target) DO UPDATE SET owner=excluded.owner,expires=excluded.expires',(target,owner,now+ttl))
            return True

    def renew_target(self, target, owner, now, ttl=30.0):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            cur=db.execute('UPDATE target_claims SET expires=? WHERE target=? AND owner=? AND expires>?',(now+ttl,target,owner,now))
            return cur.rowcount == 1

    def release_target(self, target, owner):
        with self._connect() as db:
            db.execute('DELETE FROM target_claims WHERE target=? AND owner=?',(target,owner))

    def reserve_budget(self, run_id, amount, limit):
        if amount <= 0: return True
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM budget_reservations WHERE run_id=?',(run_id,)).fetchone(): return True
            spent=db.execute("SELECT value FROM guard_meta WHERE key='spent'").fetchone()[0]
            reserved=db.execute('SELECT COALESCE(SUM(amount),0) FROM budget_reservations').fetchone()[0]
            if limit >= 0 and spent + reserved + amount > limit: return False
            db.execute("INSERT INTO budget_reservations(run_id,amount,created) VALUES (?,?,strftime('%s','now'))",(run_id,amount)); return True
    def release_budget(self, run_id):
        with self._connect() as db: db.execute('DELETE FROM budget_reservations WHERE run_id=?',(run_id,))

    def try_claim_startup(self, name, owner, now, ttl=30.0):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT owner,expires FROM startup_leases WHERE name=?',(name,)).fetchone()
            if row and row[1] > now and row[0] != owner: return False
            db.execute('INSERT INTO startup_leases(name,owner,expires) VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,expires=excluded.expires',(name,owner,now+ttl))
            return True
    def release_startup(self, name, owner):
        with self._connect() as db: db.execute('DELETE FROM startup_leases WHERE name=? AND owner=?',(name,owner))

    def recover_budget_reservations(self, *, now=None, min_age=0, evidence_limit=100):
        """Release every eligible reservation while bounding returned evidence.

        The authoritative mutation is complete; only the diagnostic sample is capped.
        """
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            import time
            now=time.time() if now is None else now
            released=[]; released_count=0; after=0
            while True:
                rows=db.execute('SELECT r.rowid,r.run_id,r.created,e.status FROM budget_reservations r LEFT JOIN effects e ON e.run_id=r.run_id WHERE r.rowid>? ORDER BY r.rowid LIMIT 500',(after,)).fetchall()
                if not rows:break
                after=rows[-1][0]
                for _rowid,run_id,created,status in rows:
                    terminal=status in (EffectStatus.FAILED.value, EffectStatus.VERIFIED.value)
                    stale_orphan=status is None and created <= now-min_age
                    if terminal or stale_orphan:
                        db.execute('DELETE FROM budget_reservations WHERE run_id=?',(run_id,)); released_count+=1
                        if len(released)<max(0,evidence_limit):released.append(run_id)
            return released_count,tuple(released)
