"""Durable, evidence-minimal primary HumanModel review transitions.

This is a notification/audit projection, NOT approval authority. It shares the
existing work SQLite database; it never creates a second data store, task or
HumanModel source evidence copy. The local UI retains a bounded question/answer
summary, separate from authority or effect execution. The caller owns review,
source and Guard verification.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path

from .human_operations import HumanNotice

_JOB = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_OUTCOMES = frozenset({
    "MATCHED_EXISTING_DELEGATION",
    "NO_MATCHING_EVIDENCE",
    "EXISTING_GUARD_DENIED",
    "APPROVED_VIEW_UNAVAILABLE",
    "REVIEW_TECHNICAL_FAILURE",
})
# Owner-level handoff only for a currently waiting canonical task. Guard denial
# is a denial, never a request to override the existing Guard automatically.
_OWNER_REVIEW_OUTCOMES = frozenset({
    "NO_MATCHING_EVIDENCE", "APPROVED_VIEW_UNAVAILABLE",
})
_SCHEMA = """
CREATE TABLE IF NOT EXISTS primary_review_transitions (
    job_id TEXT NOT NULL,
    generation_sha256 TEXT NOT NULL,
    event TEXT NOT NULL CHECK(event IN ('PRIMARY_REVIEW_STARTED','PRIMARY_REVIEW_RESOLVED')),
    outcome TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL DEFAULT '',
    answer_text TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    PRIMARY KEY (job_id, generation_sha256, event)
);
CREATE INDEX IF NOT EXISTS idx_primary_review_created
    ON primary_review_transitions(created_at DESC,job_id);
"""


def _validate(job_id, generation_sha256):
    if not isinstance(job_id, str) or not _JOB.fullmatch(job_id):
        raise ValueError("invalid primary review job identity")
    if not isinstance(generation_sha256, str) or not _DIGEST.fullmatch(generation_sha256):
        raise ValueError("exact review generation digest required")


class PrimaryReviewTransitions:
    """Write only real producer transitions to an already existing work DB."""

    def __init__(self, work_db):
        self.path = Path(work_db)
        if not self.path.is_file() or self.path.is_symlink():
            raise FileNotFoundError("existing, non-symlink work database required")
        with sqlite3.connect(self.path, timeout=5) as db:
            if not db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='work_steps'"
            ).fetchone():
                raise ValueError("existing canonical work schema required")
            db.executescript(_SCHEMA)
            # Only the real producer migrates. Presentation remains read-only
            # and continues to support historical hash-only records.
            db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in db.execute(
                "PRAGMA table_info(primary_review_transitions)")}
            if "answer_text" not in columns:
                db.execute("ALTER TABLE primary_review_transitions "
                           "ADD COLUMN answer_text TEXT NOT NULL DEFAULT ''")

    def started(self, job_id, generation_sha256):
        _validate(job_id, generation_sha256)
        with sqlite3.connect(self.path, timeout=5) as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO primary_review_transitions "
                "(job_id,generation_sha256,event,outcome) VALUES (?,?,?,?)",
                (job_id, generation_sha256, "PRIMARY_REVIEW_STARTED", "STARTED"),
            )
            return cursor.rowcount == 1

    def resolved(self, job_id, generation_sha256, outcome, *, evidence_sha256="",
                 answer_text=""):
        _validate(job_id, generation_sha256)
        if outcome not in _OUTCOMES:
            raise ValueError("invalid primary review outcome")
        if (type(answer_text) is not str or len(answer_text) > 16000
                or (answer_text and outcome != "MATCHED_EXISTING_DELEGATION")):
            raise ValueError("invalid primary review answer summary")
        if evidence_sha256 and (not isinstance(evidence_sha256, str)
                                or not _DIGEST.fullmatch(evidence_sha256)):
            raise ValueError("only an evidence digest may be persisted")
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("BEGIN IMMEDIATE")
            started = db.execute(
                "SELECT 1 FROM primary_review_transitions WHERE "
                "job_id=? AND generation_sha256=? AND event='PRIMARY_REVIEW_STARTED'",
                (job_id, generation_sha256),
            ).fetchone()
            if not started:
                raise ValueError("primary review has not started")
            existing = db.execute(
                "SELECT outcome,evidence_sha256,answer_text FROM primary_review_transitions WHERE "
                "job_id=? AND generation_sha256=? AND event='PRIMARY_REVIEW_RESOLVED'",
                (job_id, generation_sha256),
            ).fetchone()
            if existing:
                if (existing[:2] != (outcome, evidence_sha256)
                        or (existing[2] and existing[2] != answer_text)):
                    raise ValueError("conflicting primary review result")
                return False
            db.execute(
                "INSERT INTO primary_review_transitions "
                "(job_id,generation_sha256,event,outcome,evidence_sha256,answer_text) VALUES (?,?,?,?,?,?)",
                (job_id, generation_sha256, "PRIMARY_REVIEW_RESOLVED",
                 outcome, evidence_sha256, answer_text),
            )
            return True


def primary_review_notices(work_db, *, limit=128):
    """Read the existing event source for Operator UI, /api/human and Web Push.

    No schema initialization, external source read or filesystem creation on
    the presentation polling path. Raw HumanModel evidence is never exposed;
    the bounded generated answer summary is local UI/API data, not push text.
    """
    path = Path(work_db)
    if not path.is_file():
        return ()
    if type(limit) is not int or not 1 <= limit <= 256:
        raise ValueError("invalid primary review projection limit")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5) as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='primary_review_transitions'"
        ).fetchone()
        if not exists:
            return ()
        columns = {row[1] for row in db.execute(
            "PRAGMA table_info(primary_review_transitions)")}
        answer_column = "answer_text" if "answer_text" in columns else "''"
        rows = db.execute(
            "SELECT job_id,generation_sha256,event,outcome,evidence_sha256,created_at," + answer_column + " "
            "FROM primary_review_transitions ORDER BY created_at DESC,rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        observed_work = {}
        jobs = sorted({row[0] for row in rows})
        if jobs:
            marks = ",".join("?" for _ in jobs)
            for job, status in db.execute(
                    "SELECT DISTINCT job_id,status FROM work_steps WHERE job_id IN (" + marks + ")",
                    tuple(jobs)):
                observed_work.setdefault(job, set()).add(status)
        # Project only jobs present in this bounded review window. A global
        # scan of every WAITING_HUMAN job at each WebPush poll is unnecessary.
        candidates = sorted({job_id for job_id, _gen, event, outcome, *_ in rows
                             if event == "PRIMARY_REVIEW_RESOLVED"
                             and outcome in _OWNER_REVIEW_OUTCOMES})
        waiting = set()
        if candidates:
            marks = ",".join("?" for _ in candidates)
            waiting = {
                row[0] for row in db.execute(
                    "SELECT DISTINCT job_id FROM work_steps "
                    "WHERE status='WAITING_HUMAN' AND job_id IN (" + marks + ")",
                    tuple(candidates),
                ).fetchall()
            }
    notices = []
    # A newer question generation supersedes an older unmatched decision.
    latest_generation = {}
    for job_id, generation, *_rest in rows:
        latest_generation.setdefault(job_id, generation)
    for job_id, generation, event, outcome, evidence_sha256, timestamp, answer_text in rows:
        _validate(job_id, generation)
        if event not in ("PRIMARY_REVIEW_STARTED", "PRIMARY_REVIEW_RESOLVED"):
            continue
        subject = "primary-" + hashlib.sha256(
            (job_id + "\0" + generation).encode()
        ).hexdigest()[:24] + ("-start" if event == "PRIMARY_REVIEW_STARTED" else "-result")
        level = 3 if outcome == "REVIEW_TECHNICAL_FAILURE" else 2
        if event == "PRIMARY_REVIEW_STARTED":
            summary = "HumanModel一次判断を開始しました。"
            detail = f"タスク {job_id}、判断世代SHA256 {generation} の既存判断を確認中です。"
        else:
            summary = ("HumanModelによる自動回答を記録しました。"
                       if (answer_text and outcome == "MATCHED_EXISTING_DELEGATION"
                           and type(evidence_sha256) is str
                           and _DIGEST.fullmatch(evidence_sha256))
                       else "HumanModel一次判断の結果を記録しました。")
            descriptions = {
                "MATCHED_EXISTING_DELEGATION": "既存委任との照合結果です。Guard再検証は別途必須です。",
                "NO_MATCHING_EVIDENCE": "該当する明示的な判断記録がありません。新しい承認は発行しません。",
                "EXISTING_GUARD_DENIED": "既存Guardの許可範囲外です。HumanModelからの承認は発行しません。",
                "APPROVED_VIEW_UNAVAILABLE": "承認済みViewを参照できません。判断権限は発行しません。",
                "REVIEW_TECHNICAL_FAILURE": "一次判断に技術的な障害が発生しました。権限判断は停止中です。",
            }
            detail = (f"タスク {job_id}、判断世代SHA256 {generation}、"
                      f"結果 {outcome}。{descriptions.get(outcome, '結果が不明です。')}"
                      + (f" 記録参照SHA256 {evidence_sha256}。" if evidence_sha256 else ""))
        # Only source-backed provisional answers may enter the Operator/API.
        # A missing/malformed evidence digest is not an affirmative HumanModel
        # result, even if an older stored event happens to carry answer_text.
        display = (answer_text if event == "PRIMARY_REVIEW_RESOLVED"
                   and outcome == "MATCHED_EXISTING_DELEGATION"
                   and type(evidence_sha256) is str
                   and _DIGEST.fullmatch(evidence_sha256)
                   and type(answer_text) is str and 0 < len(answer_text) <= 16000
                   else "")
        if display:
            states = observed_work.get(job_id, set())
            work_status = next((state for state in (
                "UNCERTAIN", "FAILED", "WAITING_HUMAN", "RECOVERING", "RUNNING", "PLANNED")
                if state in states), "VERIFIED" if states == {"VERIFIED"} else "UNVERIFIED")
            current = latest_generation.get(job_id) == generation
            detail += (f" 関連タスク状態 {work_status}。"
                       + ("現行の判断です。" if current else "過去の判断履歴です。")
                       + "自動回答の記録は、回答の適用や処理完了の証明とは別です。異議・訂正はMuseなどから、"
                       f"タスク {job_id} と判断世代SHA256 {generation} を指定して指示してください。")
            reference = {"task_id": job_id, "question_digest": generation,
                         "evidence_sha256": evidence_sha256, "current_generation": current,
                         "related_work_status": work_status}
        else:
            reference = None
        notices.append(HumanNotice(level, "primary_review", subject, event,
                                   summary, detail, False, False, float(timestamp),
                                   automatic_answer=display, answer_reference=reference))
        if (event == "PRIMARY_REVIEW_RESOLVED"
                and outcome in _OWNER_REVIEW_OUTCOMES
                and job_id in waiting
                and latest_generation.get(job_id) == generation):
            # This is a notification handoff, not a Guard request, UI approval
            # button, human response or automatic authorization. Exact work
            # identity stays in the local Operator only, never the push body.
            notices.append(HumanNotice(
                4, "primary_review_escalation",
                subject + "-owner", "OWNER_REVIEW_REQUIRED",
                "HumanModelの一次判断では確定できませんでした。",
                f"タスク {job_id} の現行判断世代 {generation} は保留中です。"
                "本人確認が必要です。Guardの許可は発行されていません。",
                False, False, float(timestamp),
            ))
    return tuple(notices)

