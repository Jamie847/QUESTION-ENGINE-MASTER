"""Invisible spend brakes for an open dashboard (WO-005 §3)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, Request
from sqlalchemy import select

from swarm.db import session_scope
from swarm.orm import RunRow
from swarm.settings import get_settings

log = logging.getLogger("dashboard")

_last_accepted: dict[str, datetime] = {}


def reset_for_tests() -> None:
    _last_accepted.clear()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def runs_started_today() -> int:
    today = datetime.now(timezone.utc).date()
    with session_scope() as session:
        stamps = list(session.scalars(select(RunRow.started_at)))
    count = 0
    for stamp in stamps:
        if stamp is None:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        if stamp.astimezone(timezone.utc).date() == today:
            count += 1
    return count


def refuse_if_over_ceiling() -> None:
    settings = get_settings()
    cap = settings.max_runs_per_day
    used = runs_started_today()
    if used >= cap:
        log.error(
            "MAX_RUNS_PER_DAY exceeded: %s runs today (cap %s). Refusing POST /api/run",
            used,
            cap,
        )
        raise HTTPException(
            429,
            f"Daily run ceiling reached ({cap}). Try again tomorrow.",
        )


def refuse_if_cooling_down(request: Request) -> None:
    settings = get_settings()
    window = settings.run_cooldown_seconds
    if window <= 0:
        return
    ip = client_ip(request)
    now = datetime.now(timezone.utc)
    last = _last_accepted.get(ip)
    if last is not None:
        elapsed = (now - last).total_seconds()
        if elapsed < window:
            remain = int(window - elapsed) + 1
            log.warning(
                "run cooldown: ip=%s refused (%ss remaining of %ss)",
                ip,
                remain,
                window,
            )
            raise HTTPException(
                429,
                f"A run was just accepted. Wait {remain}s.",
            )


def mark_accepted(request: Request) -> None:
    if get_settings().run_cooldown_seconds <= 0:
        return
    _last_accepted[client_ip(request)] = datetime.now(timezone.utc)
