"""Daily cap on public Archive memory searches."""

from __future__ import annotations

from datetime import date, timezone

from swarm.db import session_scope
from swarm.orm import MemorySearchDayRow
from swarm.settings import get_settings

_forced_day: str | None = None


def force_day(day: str | None) -> None:
    global _forced_day
    _forced_day = day


def today_iso() -> str:
    return _forced_day or date.today().isoformat()


def reset_day(day: str) -> None:
    force_day(day)
    with session_scope() as session:
        row = session.get(MemorySearchDayRow, day)
        if row is not None:
            session.delete(row)


def remaining_searches(day: str | None = None) -> int:
    settings = get_settings()
    cap = max(0, int(settings.memory_searches_per_day))
    used = _used(day or today_iso())
    return max(0, cap - used)


def take_search(day: str | None = None) -> bool:
    settings = get_settings()
    cap = max(0, int(settings.memory_searches_per_day))
    when = day or today_iso()
    with session_scope() as session:
        row = session.get(MemorySearchDayRow, when)
        if row is None:
            row = MemorySearchDayRow(day=when, count=0)
            session.add(row)
        if row.count >= cap:
            return False
        row.count += 1
        return True


def _used(day: str) -> int:
    with session_scope() as session:
        row = session.get(MemorySearchDayRow, day)
        return int(row.count) if row is not None else 0


# timezone imported for callers that want UTC; keep the module honest
_ = timezone
