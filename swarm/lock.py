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


def current_lock(name: str = "daily") -> RunLockRow | None:
    with session_scope() as session:
        return session.scalar(select(RunLockRow).where(RunLockRow.name == name))


def locked_run_id(name: str = "daily") -> int | None:
    """Copy the lock's run id out of the session so callers can use it."""
    with session_scope() as session:
        row = session.scalar(select(RunLockRow).where(RunLockRow.name == name))
        return int(row.run_id) if row is not None and row.run_id is not None else None


def fail_unlocked_running_runs(keep_id: int | None = None) -> int:
    """Close running rows that no longer hold the daily lock.

    A deploy mid-run leaves status=running with no worker. The banner and
    /api/status used to treat that row as live. This is crash recovery, not
    the WO-011 link rewrite — it only flips orphaned run rows.
    """
    hold = keep_id if keep_id is not None else locked_run_id()
    now = datetime.now(timezone.utc)
    closed = 0
    with session_scope() as session:
        rows = list(session.scalars(select(RunRow).where(RunRow.status == "running")))
        for row in rows:
            if hold is not None and row.id == hold:
                continue
            row.status = "failed"
            row.error = "orphaned — lock gone (instance stopped mid-run)"
            row.finished_at = now
            closed += 1
    return closed
