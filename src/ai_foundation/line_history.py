"""Owner-scoped LINE history intake. No network, LLM, or automatic KLM effects.

The source is the user's explicitly exported chat TXT or opt-in Android captures.
Raw third-party speech stays in this private, local source store; KLM receives
only source pointers after separate authorization.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo

from .knowledge_lifecycle import SourcePointer

SCHEMA = "line-capture/v1"
SOURCES = frozenset({"txt", "notification", "screen"})
DIRECTIONS = frozenset({"incoming", "outgoing", "outgoing_candidate", "unknown"})
DATE_RE = re.compile(r"^\s*\[?(\d{4})[./-](\d{1,2})[./-](\d{1,2})(?:\([^\n)]*\))?\]?\s*$")
MESSAGE_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\t([^\t]+)\t(.*)$")
MAX_EVENT_TEXT = 100_000
MAX_TXT_BYTES = 32 * 1024 * 1024


def _hash(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _iso(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be ISO-8601 with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("invalid ISO timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone required")
    return parsed.isoformat()


def _identity(value, field):
    if not isinstance(value, str) or not 0 < len(value) <= 300 or "\x00" in value:
        raise ValueError(f"explicit bounded {field} required")
    return value


def parse_line_txt(raw: bytes, *, conversation_key: str, self_names: tuple[str, ...], tz="Asia/Tokyo"):
    """Yield exact-order text observations; never infer missing chats or media bytes.

    Supports LINE tab-delimited Japanese/English exports with dated sections.
    Repeated equal messages within a minute receive separate ordinal identities.
    Unrecognized records are returned in the receipt, not silently called complete.
    """
    _identity(conversation_key, "conversation")
    if (type(self_names) not in (tuple, list) or not self_names
            or any(type(n) is not str or not n.strip() or len(n) > 300
                   for n in self_names)):
        raise ValueError("explicit self_names required to attribute outgoing messages")
    if not isinstance(raw, bytes) or len(raw) > MAX_TXT_BYTES:
        raise ValueError("TXT input must be bytes <=32 MiB (split into individual exports)")
    try:
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            data = raw.decode("utf-16")
        else:
            data = raw.decode("utf-8-sig")
    except UnicodeError:
        raise ValueError("unsupported TXT encoding") from None
    zone = ZoneInfo(tz)
    current_date = None
    pending = None
    parsed = []
    unparsed = []
    def flush():
        nonlocal pending
        if pending is not None:
            parsed.append(pending)
            pending = None
    for line_no, line in enumerate(data.splitlines(), 1):
        date_match = DATE_RE.match(line)
        if date_match:
            flush()
            y, m, d = map(int, date_match.groups())
            try:
                current_date = datetime(y, m, d).date()
            except ValueError:
                raise ValueError(f"invalid date at line {line_no}") from None
            continue
        message = MESSAGE_RE.match(line)
        if message and current_date is not None:
            flush()
            hour, minute, second = (int(message[1]), int(message[2]), int(message[3] or 0))
            try:
                when = datetime(current_date.year, current_date.month, current_date.day,
                                hour, minute, second, tzinfo=zone)
            except ValueError:
                raise ValueError(f"invalid message time at line {line_no}") from None
            actor = message[4].strip()
            pending = {"time": when.isoformat(), "actor": actor, "text": message[5],
                       "line_no": line_no}
            continue
        if pending is not None:
            pending["text"] += "\n" + line
        elif line.strip() and not (line.startswith("[LINE]") or
                                   line.startswith("保存日時") or
                                   line.lower().startswith("saved on")):
            unparsed.append(line_no)
    flush()
    ordinal = Counter()
    events = []
    for item in parsed:
        if not item["actor"]:
            unparsed.append(item["line_no"])
            continue
        if len(item["text"]) > MAX_EVENT_TEXT:
            raise ValueError(f"message exceeds safe bound at line {item['line_no']}")
        base = (conversation_key, item["time"], item["actor"], item["text"])
        ordinal[base] += 1
        events.append({
            "schema": SCHEMA, "kind": "message", "source": "txt",
            "source_event_id": "txt:" + _hash((base, ordinal[base])),
            "conversation_key": conversation_key,
            "actor": item["actor"],
            "direction": "outgoing" if item["actor"] in self_names else "incoming",
            "text": item["text"], "event_time": item["time"],
            "observed_at": item["time"], "quality": "USER_SUPPLIED_EXPORT",
        })
    return events, {"parsed": len(events), "unparsed_lines": tuple(unparsed),
                    "range_start": min((x["event_time"] for x in events), default=None),
                    "range_end": max((x["event_time"] for x in events), default=None),
                    "complete": False, "reason": "EXPORT_OF_ONE_CHAT_NOT_ACCOUNT_INVENTORY"}


class LineHistoryArchive:
    """Strict owner-local SQLite source archive, not a parallel KLM or HumanModel."""

    def __init__(self, path: str | Path, *, owner: str):
        self.owner = _identity(owner, "owner")
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise PermissionError("symlink database forbidden")
        if not self.path.exists():
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(fd)
        if self.path.is_symlink() or self.path.stat().st_mode & 0o077:
            raise PermissionError("private LINE archive must be mode 0600")
        with self._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS line_archive_owner(owner TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS line_observations(
                event_id TEXT PRIMARY KEY, owner TEXT NOT NULL, source TEXT NOT NULL,
                source_event_id TEXT NOT NULL, conversation_key TEXT NOT NULL,
                actor TEXT, direction TEXT NOT NULL, body TEXT NOT NULL,
                event_time TEXT, observed_at TEXT NOT NULL, quality TEXT NOT NULL,
                UNIQUE(owner, source, source_event_id)
            );
            CREATE INDEX IF NOT EXISTS line_by_chat
                ON line_observations(owner, conversation_key, event_time);
            CREATE TABLE IF NOT EXISTS line_coverage(
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, source TEXT NOT NULL,
                start_at TEXT NOT NULL, end_at TEXT, state TEXT NOT NULL
            );
            """)
        with self._db() as db:
            owners = db.execute("SELECT owner FROM line_archive_owner LIMIT 2").fetchall()
            if owners and (len(owners) != 1 or owners[0]["owner"] != self.owner):
                raise PermissionError("LINE archive belongs to a different owner")
            db.execute("INSERT OR IGNORE INTO line_archive_owner(owner) VALUES(?)", (self.owner,))
        os.chmod(self.path, 0o600)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def ingest(self, observations):
        """Idempotent, single-transaction capture."""
        with self._db() as db:
            return self._ingest_into(db, observations)

    def _ingest_into(self, db, observations):
        """Share one SQLite transaction across one or many imported exports."""
        added = already = 0
        for event in observations:
            if not isinstance(event, dict) or event.get("schema") != SCHEMA:
                raise ValueError("line-capture/v1 event required")
            source = event.get("source")
            if source not in SOURCES:
                raise ValueError("unsupported LINE observation source")
            eid = _identity(event.get("source_event_id"), "source event id")
            if event.get("kind") == "coverage":
                start = _iso(event.get("observed_at"))
                end = _iso(event["event_time"]) if event.get("event_time") else None
                state = event.get("quality")
                if state not in {"LISTENER_CONNECTED", "LISTENER_DISCONNECTED", "SCREEN_ENABLED",
                                 "SCREEN_DISABLED", "EXPORT_IMPORTED", "CAPTURE_ERROR"}:
                    raise ValueError("unsupported coverage state")
                key = _hash((self.owner, source, eid))
                row = db.execute("INSERT OR IGNORE INTO line_coverage VALUES(?,?,?,?,?,?)",
                                 (key, self.owner, source, start, end, state))
            elif event.get("kind") == "message":
                chat = _identity(event.get("conversation_key"), "conversation key")
                direction = event.get("direction")
                if direction not in DIRECTIONS:
                    raise ValueError("direction must be explicit or unknown")
                body = event.get("text")
                if not isinstance(body, str) or len(body) > MAX_EVENT_TEXT:
                    raise ValueError("bounded original text required")
                actor = event.get("actor")
                if actor is not None:
                    _identity(actor, "actor")
                observed = _iso(event.get("observed_at"))
                when = _iso(event["event_time"]) if event.get("event_time") else None
                quality = _identity(event.get("quality"), "quality")
                if source == "screen" and quality != "UNVERIFIED_UI_TEXT":
                    raise ValueError("UI text is never verified chat history")
                if source == "notification" and direction == "outgoing":
                    raise ValueError("notification cannot certify self-sent")
                if source == "txt" and quality != "USER_SUPPLIED_EXPORT":
                    raise ValueError("TXT evidence classification required")
                key = _hash((self.owner, source, eid))
                row = db.execute("""INSERT OR IGNORE INTO line_observations
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (key, self.owner, source, eid, chat, actor, direction, body,
                     when, observed, quality))
            else:
                raise ValueError("unsupported LINE event kind")
            if row.rowcount:
                added += 1
            else:
                if event["kind"] == "message":
                    existing = db.execute("""SELECT conversation_key,actor,direction,body,
                            quality,event_time,observed_at
                        FROM line_observations WHERE event_id=? LIMIT 1""", (key,)).fetchone()
                    # TXT IDs bind stable message time; an Android notification
                    # may be seen again later with a different observed_at.
                    # A screen key can be re-observed within one 30s bucket
                    # with both timestamps changed. Never alter original data.
                    if existing is None or (
                        existing["conversation_key"], existing["actor"],
                        existing["direction"], existing["body"], existing["quality"]
                    ) != (chat, actor, direction, body, quality):
                        raise ValueError("SOURCE_EVENT_ID_CONFLICT")
                    if ((source == "txt" and
                         (existing["event_time"], existing["observed_at"])
                         != (when, observed))
                            or (source == "notification" and
                                existing["event_time"] != when)):
                        raise ValueError("SOURCE_EVENT_ID_CONFLICT")
                else:
                    existing = db.execute("""SELECT state,start_at,end_at
                        FROM line_coverage WHERE id=? LIMIT 1""", (key,)).fetchone()
                    if existing is None or (
                        existing["state"], existing["start_at"], existing["end_at"]
                    ) != (state, start, end):
                        raise ValueError("SOURCE_EVENT_ID_CONFLICT")
                already += 1
        return {"inserted": added, "already_present": already}

    def import_txt_batch(self, exports, *, tz="Asia/Tokyo"):
        """Atomically import bounded sequential TXT exports, including self-sent.

        exports is a local iterator of (raw bytes, room key, owner aliases).
        The caller may stream one file at a time, without holding all history
        in memory. Any parse, mapping or source error rolls back all rooms.
        """
        totals = {"exports_processed": 0, "parsed": 0, "inserted": 0,
                  "already_present": 0, "files_with_unparsed_lines": 0,
                  "account_complete": False}
        with self._db() as db:
            for raw, room, names in exports:
                events, receipt = parse_line_txt(
                    raw, conversation_key=room, self_names=names, tz=tz)
                count = self._ingest_into(db, events)
                totals["exports_processed"] += 1
                totals["parsed"] += receipt["parsed"]
                totals["inserted"] += count["inserted"]
                totals["already_present"] += count["already_present"]
                totals["files_with_unparsed_lines"] += bool(receipt["unparsed_lines"])
        return totals

    def import_txt(self, raw, *, conversation_key, self_names, tz="Asia/Tokyo"):
        events, receipt = parse_line_txt(raw, conversation_key=conversation_key,
                                          self_names=self_names, tz=tz)
        receipt.update(self.ingest(events))
        return receipt

    def status(self):
        with self._db() as db:
            counts = db.execute("""SELECT source,direction,COUNT(*) n FROM line_observations
                WHERE owner=? GROUP BY source,direction""", (self.owner,)).fetchall()
            missing = db.execute("""SELECT COUNT(*) FROM line_observations
                WHERE owner=? AND (quality='UNVERIFIED_UI_TEXT'
                          OR conversation_key LIKE 'screen:%')""", (self.owner,)).fetchone()[0]
            boundaries = db.execute("""SELECT source,state,COUNT(*) n FROM line_coverage
                WHERE owner=? GROUP BY source,state""", (self.owner,)).fetchall()
        return {"by_source_direction": {(x["source"], x["direction"]): x["n"] for x in counts},
                "unverified_screen_observations": missing,
                "service_coverage_markers": {(x["source"], x["state"]): x["n"] for x in boundaries},
                "account_complete": False,
                "limitations": ("No LINE-wide official chat inventory",
                                "Notifications may be missing or redacted",
                                "Screen content is only an unverified candidate",
                                "Unseen self-sent messages cannot be certified")}

    def klm_source_pointers(self, *, limit=100):
        """Provenance only; does not authorize KLM input or publish private text."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("bounded pointer query required")
        with self._db() as db:
            rows = db.execute("""SELECT event_id,conversation_key,observed_at
                FROM line_observations WHERE owner=? AND source='txt'
                ORDER BY event_id LIMIT ?""", (self.owner, limit)).fetchall()
        return tuple(SourcePointer(
            system="other", resource_id="line-history:" + _hash((self.owner, row["conversation_key"])),
            record_id=row["event_id"], revision="source-event/v1",
            scope=self.owner, privacy="private", observed_at=row["observed_at"],
            actor_claim="unknown") for row in rows)

    def reconcile_export_window(self, *, conversation_key, capture_keys, tolerance_seconds=180):
        """Compare one owner-exported room with explicitly mapped live capture rooms.

        A match is only a cross-source *candidate*; it neither authenticates actor
        nor establishes continuous notification/screen coverage. No raw text exits.
        """
        chat = _identity(conversation_key, "conversation key")
        if type(capture_keys) not in (tuple, list) or not 1 <= len(capture_keys) <= 20:
            raise ValueError("explicit bounded capture chat mapping required")
        keys = tuple(_identity(k, "capture chat") for k in capture_keys)
        if "screen:unresolved" in keys:
            raise ValueError("unresolved screen chat cannot identify conversation")
        if type(tolerance_seconds) is not int or not 0 <= tolerance_seconds <= 3600:
            raise ValueError("bounded comparison time window required")
        with self._db() as db:
            expected = db.execute("""SELECT event_id,body,event_time,direction
                FROM line_observations WHERE owner=? AND conversation_key=? AND source='txt'
                ORDER BY event_time,event_id""", (self.owner, chat)).fetchall()
            placeholders = ",".join("?" for _ in keys)
            observed = db.execute("""SELECT event_id,body,event_time,observed_at,source,direction
                FROM line_observations WHERE owner=? AND source IN ('screen','notification')
                AND conversation_key IN (""" + placeholders + """)
                ORDER BY event_time,event_id""", (self.owner, *keys)).fetchall()
        used = set()
        candidate = uncertain = unseen = 0
        ids = []
        for truth in expected:
            when = datetime.fromisoformat(truth["event_time"]).timestamp()
            matches = []
            for other in observed:
                if other["event_id"] in used or other["body"] != truth["body"]:
                    continue
                if truth["direction"] == "outgoing":
                    if not (other["source"] == "screen" and
                            other["direction"] == "outgoing_candidate"):
                        continue
                elif truth["direction"] == "incoming":
                    if other["source"] == "screen" and other["direction"] == "outgoing_candidate":
                        continue
                else:
                    continue
                observed_time = other["event_time"] or other["observed_at"]
                if abs(datetime.fromisoformat(observed_time).timestamp() - when) <= tolerance_seconds:
                    matches.append(other)
            if len(matches) == 1:
                used.add(matches[0]["event_id"])
                candidate += 1
            elif len(matches) > 1:
                uncertain += 1
                ids.append(truth["event_id"])
            else:
                unseen += 1
                ids.append(truth["event_id"])
        return {"exported_messages": len(expected), "live_match_candidates": candidate,
                "ambiguous_matches": uncertain, "not_observed_in_live_capture": unseen,
                "unresolved_export_event_ids": tuple(ids),
                "coverage_certified": False,
                "reason": "SOURCE_CONTENT_MATCH_IS_NOT_COMPLETE_HISTORY_OR_ACTOR_PROOF"}
