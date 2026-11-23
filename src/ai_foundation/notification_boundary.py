"""Notification projection over Foundation human semantics; transport is replaceable.

Malformed input is inert. Valid notices retain the original level, duplicate
suppression and privacy boundaries; no external delivery occurs here.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PushNotice:
    key: str
    title: str
    body: str
    level: int


def project_push(
    payload: dict,
    seen: frozenset[str] = frozenset(),
) -> tuple[PushNotice, ...]:
    """Project only structurally valid notice collections."""
    if type(payload) is not dict:
        return ()

    notices = payload.get("notices", ())
    # Reject strings, maps and unbounded iterators before processing any row.
    if type(notices) not in (list, tuple):
        return ()

    emitted = set(seen)
    output = []
    for notice in notices:
        # One malformed row must not suppress later valid notifications.
        if type(notice) is not dict:
            continue
        level = notice.get("level", 1)
        if type(level) is not int or level < 1:
            continue

        status = notice.get("status")
        key = (
            f"{notice.get('kind', 'system')}:"
            f"{notice.get('subject', '')}:"
            f"{notice.get('status', '')}"
        )
        if key in emitted:
            continue

        primary = (
            level == 2
            and notice.get("kind") == "primary_review"
            and type(status) is str
            and status in ("PRIMARY_REVIEW_STARTED", "PRIMARY_REVIEW_RESOLVED")
        )
        if level < 3 and not primary:
            continue

        if primary:
            title = "HumanModel一次判断"
            body = (
                "一次判断を開始しました。"
                if status == "PRIMARY_REVIEW_STARTED"
                else "一次判断の結果が更新されました。"
            )
        elif (
            level == 4
            and notice.get("kind") == "primary_review_escalation"
            and status == "OWNER_REVIEW_REQUIRED"
        ):
            # Avoid exporting a producer-controlled private summary in pushes.
            title = "本人確認が必要です"
            body = "HumanModelの一次判断が未解決です。Foundationで内容を確認してください。"
        else:
            title = "確認が必要です" if level >= 4 else "Foundationからのお知らせ"
            body = str(notice.get("summary_ja") or "状態を確認してください。")[:240]

        output.append(PushNotice(key, title, body, level))
        emitted.add(key)

    return tuple(output)
