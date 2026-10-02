"""Operator-facing clocks. Persist UTC; print DISPLAY_TZ."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from swarm.settings import get_settings


def zone(name: str | None = None) -> ZoneInfo:
    raw = (name or get_settings().display_tz or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(raw)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_local(dt: datetime | None, tz: str | None = None) -> datetime | None:
    utc = as_utc(dt)
    if utc is None:
        return None
    return utc.astimezone(zone(tz))


def local_date(dt: datetime | None, tz: str | None = None) -> date | None:
    local = to_local(dt, tz)
    return local.date() if local else None


def _hour_12(local: datetime) -> str:
    hour = local.strftime("%I").lstrip("0") or "0"
    return f"{hour}:{local.strftime('%M')} {local.strftime('%p')}"


def format_local(dt: datetime | None, tz: str | None = None) -> str:
    """Tuesday, Sep 29, 2026 · 8:30 PM MDT"""
    local = to_local(dt, tz)
    if local is None:
        return "—"
    return (
        f"{local.strftime('%A')}, {local.strftime('%b')} {local.day}, {local.year} "
        f"· {_hour_12(local)} {local.tzname() or zone(tz).key}"
    )


def format_short_date(dt: datetime | None, tz: str | None = None) -> str:
    """Sep 29, 2026"""
    local = to_local(dt, tz)
    if local is None:
        return "—"
    return f"{local.strftime('%b')} {local.day}, {local.year}"


def format_duration(started: datetime | None, finished: datetime | None) -> str:
    start = as_utc(started)
    end = as_utc(finished)
    if start is None or end is None:
        return "—"
    secs = max(0, int((end - start).total_seconds()))
    hours, rem = divmod(secs, 3600)
    mins, sec = divmod(rem, 60)
    if hours:
        return f"{hours}h {mins}m"
    if mins:
        return f"{mins}m {sec}s"
    return f"{sec}s"


def age_days_from(
    finished: datetime | None,
    *,
    as_of: datetime | None = None,
    tz: str | None = None,
) -> int | None:
    """Calendar days in DISPLAY_TZ between finished_at and now."""
    local_end = to_local(finished, tz)
    if local_end is None:
        return None
    now = to_local(as_of or datetime.now(timezone.utc), tz)
    if now is None:
        return None
    return max(0, (now.date() - local_end.date()).days)


def run_stamp(run_id: int, started: datetime | None, tz: str | None = None) -> str:
    return f"run {run_id} · {format_short_date(started, tz)}"


def run_banner(
    *,
    run_id: int,
    started: datetime | None,
    finished: datetime | None = None,
    cost_usd: float = 0.0,
    status: str = "",
    tz: str | None = None,
) -> str:
    parts = [
        f"Run #{run_id}",
        format_local(started, tz),
        format_duration(started, finished),
        f"${cost_usd:.2f}",
    ]
    if status:
        parts.append(status)
    return " · ".join(parts)
