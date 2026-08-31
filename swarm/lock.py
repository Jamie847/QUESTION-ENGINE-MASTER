from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from swarm.db import session_scope
from swarm.orm import RunLockRow
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
