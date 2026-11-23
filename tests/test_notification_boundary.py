"""Fixed, host-owned acceptance for the notification projection."""
from ai_foundation.notification_boundary import project_push


def _notice(subject, level=3, *, kind="work", status="WAITING_HUMAN"):
    return {
        "kind": kind,
        "subject": subject,
        "status": status,
        "level": level,
        "summary_ja": "確認してください。",
    }


def test_push_projection_is_foundation_native_private_and_deduplicable():
    payload = {
        "notices": [
            {
                "level": 4,
                "kind": "work",
                "subject": "j:0",
                "status": "WAITING_HUMAN",
                "summary_ja": "入力が必要です",
                "raw": "SECRET TASK TEXT",
            },
            {
                "level": 1,
                "kind": "x",
                "subject": "i",
                "status": "INFO",
                "summary_ja": "quiet",
            },
        ]
    }
    notices = project_push(payload)
    assert len(notices) == 1
    assert notices[0].body == "入力が必要です"
    assert "SECRET" not in repr(notices)
    assert project_push(payload, frozenset({notices[0].key})) == ()


def test_batch_dedup_keeps_first_valid_notice_and_external_seen():
    first = _notice("duplicate", 4)
    rows = [first, dict(first), _notice("later", 3)]
    assert [row.key for row in project_push({"notices": rows})] == [
        "work:duplicate:WAITING_HUMAN",
        "work:later:WAITING_HUMAN",
    ]
    assert [row.key for row in project_push(
        {"notices": rows}, frozenset({"work:duplicate:WAITING_HUMAN"})
    )] == ["work:later:WAITING_HUMAN"]


def test_invalid_rows_and_severities_do_not_abort_later_valid_notice():
    rows = [
        None,
        "bad",
        [],
        _notice("invalid-text", "critical"),
        _notice("invalid-bool", True),
        _notice("invalid-float", 3.5),
        _notice("valid", 4),
    ]
    projected = project_push({"notices": rows})
    assert [row.key for row in projected] == ["work:valid:WAITING_HUMAN"]


def test_invalid_duplicate_does_not_consume_notice_key_or_change_primary_copy():
    invalid = _notice("same", "critical")
    valid = _notice("same", 4)
    primary = _notice(
        "decision", 2, kind="primary_review", status="PRIMARY_REVIEW_STARTED"
    )
    notices = project_push({"notices": [invalid, valid, primary, dict(primary)]})
    assert len(notices) == 2
    assert notices[0].key == "work:same:WAITING_HUMAN"
    assert notices[1].title == "HumanModel一次判断"
    assert notices[1].body == "一次判断を開始しました。"


def test_malformed_top_level_and_collection_are_inert():
    for payload in (None, "invalid", [], 0, True):
        assert project_push(payload) == ()
    # No map-key loops, character iteration, or unbounded generators.
    for collection in (None, "bad", {}, 0, True, set(), iter([_notice("x")])):
        assert project_push({"notices": collection}) == ()


def test_malformed_primary_status_does_not_abort_later_valid_row():
    bad = _notice("bad-status", 2, kind="primary_review", status=[])
    valid = _notice(
        "decision", 2, kind="primary_review", status="PRIMARY_REVIEW_RESOLVED"
    )
    projected = project_push({"notices": [bad, valid]})
    assert len(projected) == 1
    assert projected[0].key == "primary_review:decision:PRIMARY_REVIEW_RESOLVED"
    assert projected[0].title == "HumanModel一次判断"


def test_valid_list_and_tuple_preserve_notifications_and_safe_escalation():
    notice = _notice("ok", 4)
    expected = project_push({"notices": [notice]})
    assert expected
    assert project_push({"notices": (notice,)}) == expected
    escalation = _notice(
        "private-id",
        4,
        kind="primary_review_escalation",
        status="OWNER_REVIEW_REQUIRED",
    )
    escalation["summary_ja"] = "SECRET USER DATA"
    output = project_push({"notices": [escalation]})
    assert len(output) == 1
    assert output[0].title == "本人確認が必要です"
    assert "SECRET" not in repr(output)
