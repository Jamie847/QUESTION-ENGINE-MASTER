from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from swarm.db import session_scope
from swarm.orm import RunLockRow, RunRow
from swarm.settings import get_settings


class LockBusy(RuntimeError):
    pass


def acquire_lock(run_id: int, name: str = "daily") -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=settings.lock_stale_after_s)
    with session_scope() as session:
        row = session.get(RunLockRow, name)
        if row is None:
            session.add(RunLockRow(name=name, run_id=run_id, acquired_at=now))
            return
        acquired = row.acquired_at
        if acquired is not None and acquired.tzinfo is None:
            acquired = acquired.replace(tzinfo=timezone.utc)
        if acquired and acquired > stale_before:
            raise LockBusy(f"swarm already running (run_id={row.run_id})")
        row.run_id = run_id
        row.acquired_at = now


def release_lock(name: str = "daily") -> None:
    with session_scope() as session:
        row = session.get(RunLockRow, name)
        if row is not None:
            session.delete(row)


def _acquired_utc(acquired: datetime | None) -> datetime | None:
    if acquired is not None and acquired.tzinfo is None:
        return acquired.replace(tzinfo=timezone.utc)
    return acquired


def _stale_before() -> datetime:
    return datetime.now(timezone.utc) - timedelta(
        seconds=get_settings().lock_stale_after_s
    )


def current_lock(name: str = "daily") -> RunLockRow | None:
    """Live lock only. A row older than lock_stale_after_s (2h) is not in progress."""
    stale_before = _stale_before()
    with session_scope() as session:
        row = session.scalar(select(RunLockRow).where(RunLockRow.name == name))
        if row is None:
            return None
        acquired = _acquired_utc(row.acquired_at)
        if acquired is None or acquired <= stale_before:
            return None
        session.expunge(row)
        return row


def held_run_id(name: str = "daily") -> int | None:
    """Run id for a *live* lock. A stale lock does not block /api/run or deploy."""
    stale_before = _stale_before()
    with session_scope() as session:
        row = session.get(RunLockRow, name)
        if row is None or row.run_id is None:
            return None
        acquired = _acquired_utc(row.acquired_at)
        if acquired is None or acquired <= stale_before:
            return None
        return int(row.run_id)


def locked_run_id(name: str = "daily") -> int | None:
    """Copy the lock's run id out of the session so callers can use it."""
    with session_scope() as session:
        row = session.scalar(select(RunLockRow).where(RunLockRow.name == name))
        return int(row.run_id) if row is not None and row.run_id is not None else None


def fail_unlocked_running_runs(keep_id: int | None = None) -> int:
    """Close running rows that no longer hold a *live* lock.

    A deploy mid-run, or a worker that died and left the lock past
    lock_stale_after_s (2h), leaves status=running with no worker. A stale
    lock row is released here so /api/run and the cron can start again.
    """
    hold = keep_id if keep_id is not None else held_run_id()
    now = datetime.now(timezone.utc)
    closed = 0
    with session_scope() as session:
        if hold is None:
            leftover = session.get(RunLockRow, "daily")
            if leftover is not None:
                session.delete(leftover)
        rows = list(session.scalars(select(RunRow).where(RunRow.status == "running")))
        for row in rows:
            if hold is not None and row.id == hold:
                continue
            row.status = "failed"
            row.error = "orphaned — lock gone or stale (instance stopped mid-run)"
            row.finished_at = now
            closed += 1
    return closed


def close_orphans_on_startup() -> int:
    """Web and cron boot: fail zombies and drop a stale daily lock."""
    return fail_unlocked_running_runs()
