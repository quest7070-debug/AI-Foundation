from datetime import datetime, timedelta, timezone

from ai_foundation.auto_agent import _trusted_agent_instruction
from ai_foundation.temporal_context import TemporalContext


def test_trusted_agent_instruction_binds_host_calendar_date_for_complete_turn():
    observed=datetime(2026,9,25,22,42,6,tzinfo=timezone.utc).astimezone()
    instruction=_trusted_agent_instruction(
        "今日の日付と最新ニュースを検索して",
        lambda: TemporalContext(observed),
    )
    assert "[Host temporal context — authoritative for relative dates]" in instruction
    assert f"Calendar date: {observed.date().isoformat()}." in instruction
    assert f"Time zone: {observed.tzname() or observed.utcoffset()}." in instruction
    assert instruction.endswith("[User request]\n今日の日付と最新ニュースを検索して")


def test_trusted_agent_instruction_refreshes_temporal_context_per_run():
    host_tz=timezone(timedelta(hours=9),name="JST")
    contexts=iter((
        TemporalContext(datetime(2026,9,25,23,59,59,tzinfo=host_tz)),
        TemporalContext(datetime(2026,9,26,0,0,1,tzinfo=host_tz)),
    ))
    factory=lambda: next(contexts)
    first=_trusted_agent_instruction("current status",factory)
    second=_trusted_agent_instruction("current status",factory)
    assert "Calendar date: 2026-09-25." in first
    assert "Calendar date: 2026-09-26." in second
