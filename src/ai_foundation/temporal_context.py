"""Provider-neutral observation context for time-sensitive retrieval."""
from dataclasses import dataclass
from datetime import datetime,timezone

@dataclass(frozen=True)
class TemporalContext:
    observed_at: datetime
    def search_context(self)->str:
        dt=self.observed_at.astimezone()
        return f"Observation time: {dt.isoformat(timespec='seconds')}. Calendar date: {dt.date().isoformat()}. Time zone: {dt.tzname() or dt.utcoffset()}."

def current_temporal_context(now=None):
    return TemporalContext(now or datetime.now(timezone.utc).astimezone())
