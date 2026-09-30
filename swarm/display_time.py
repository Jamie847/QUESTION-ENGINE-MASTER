"""Render run instants in the Operator's zone. Naive timestamps are UTC."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


def zone_for(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def as_display(dt: datetime, tz_name: str) -> datetime:
    return as_utc(dt).astimezone(zone_for(tz_name))


def digest_local_date(started_at: datetime, tz_name: str) -> date:
    return as_display(started_at, tz_name).date()


def format_run_stamp(dt: datetime, tz_name: str) -> str:
    """Tuesday, Sep 29, 8:30 PM MDT — the test looks for the date-time-zone tail."""
    local = as_display(dt, tz_name)
    hour = local.strftime("%I").lstrip("0") or "12"
    zone = local.tzname() or tz_name
    return (
        f"{local.strftime('%A')}, {local.strftime('%b')} {local.day}, "
        f"{hour}:{local.strftime('%M')} {local.strftime('%p')} {zone}"
    )


def format_duration(started: datetime | None, finished: datetime | None) -> str:
    if started is None or finished is None:
        return "—"
    seconds = int((as_utc(finished) - as_utc(started)).total_seconds())
    if seconds < 0:
        seconds = 0
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def age_days_from_finished(
    finished_at: datetime, tz_name: str, *, now: datetime | None = None
) -> int:
    done = as_display(finished_at, tz_name).date()
    today = as_display(now or datetime.now(timezone.utc), tz_name).date()
    return max(0, (today - done).days)


def run_header(
    *,
    run_id: int,
    started_at: datetime,
    finished_at: datetime | None,
    tz_name: str,
    cost_usd: float,
    status: str,
) -> str:
    stamp = format_run_stamp(started_at, tz_name)
    duration = format_duration(started_at, finished_at)
    return (
        f"Run #{run_id} · {stamp} · {duration} · ${cost_usd:.2f} · {status or '—'}"
    )
