import threading

from swarm.db import init_db, session_scope
from swarm.lock import (
    LockBusy,
    acquire_lock,
    close_orphans_on_startup,
    current_lock,
    fail_unlocked_running_runs,
    held_run_id,
    locked_run_id,
    release_lock,
)
from swarm.orm import RunLockRow, RunRow


def test_second_acquire_is_rejected_on_real_session():
    """Uses session_scope (real commit), not a fake session. Against a lock
    that never persists, the second acquire would succeed and this goes red."""
    init_db()
    name = "lock-test-sequential"
    with session_scope() as session:
        session.query(RunLockRow).filter(RunLockRow.name == name).delete()
    acquire_lock(101, name=name)
    try:
        try:
            acquire_lock(102, name=name)
            raise AssertionError("second acquire should have been LockBusy")
        except LockBusy:
            pass
    finally:
        release_lock(name)


def test_concurrent_acquires_exactly_one_winner():
    init_db()
    name = "lock-test-concurrent"
    with session_scope() as session:
        session.query(RunLockRow).filter(RunLockRow.name == name).delete()

    winners: list[int] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(2)

    def _try(run_id: int) -> None:
        try:
            barrier.wait(timeout=5)
            acquire_lock(run_id, name=name)
            winners.append(run_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=_try, args=(201,))
    t2 = threading.Thread(target=_try, args=(202,))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    release_lock(name)
    assert len(winners) == 1
    assert any(isinstance(e, LockBusy) for e in errors) or len(errors) == 1


def test_unlocked_running_row_is_failed_and_not_treated_as_live():
    """A deploy-killed run stays status=running. The lock is the live signal."""
    init_db()
    release_lock()
    with session_scope() as session:
        session.query(RunRow).filter(RunRow.id == 924).delete()
        session.add(RunRow(id=924, status="running", current_stage="scout"))
    assert locked_run_id() is None
    closed = fail_unlocked_running_runs()
    assert closed >= 1
    with session_scope() as session:
        row = session.get(RunRow, 924)
        assert row is not None
        assert row.status == "failed"
        assert "orphaned" in (row.error or "")


def test_refuse_if_locked_fails_deploy_when_a_run_holds_the_lock(capsys):
    """A live lock must fail preDeploy so the old instance keeps serving."""
    from datetime import datetime, timedelta, timezone

    from swarm.orm import RunLockRow
    from swarm.run_daily import main

    init_db()
    release_lock()
    acquire_lock(26)
    assert held_run_id() == 26
    rc = main(["--refuse-if-locked"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "REFUSE_DEPLOY lock held by run 26" in out

    with session_scope() as session:
        row = session.get(RunLockRow, "daily")
        assert row is not None
        row.acquired_at = datetime.now(timezone.utc) - timedelta(seconds=8000)
    assert held_run_id() is None
    rc = main(["--refuse-if-locked"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "REFUSE_DEPLOY ok" in out

    release_lock()
    rc = main(["--refuse-if-locked"])
    assert rc == 0
    assert "REFUSE_DEPLOY ok" in capsys.readouterr().out


def test_stale_lock_is_not_in_progress_and_orphan_is_closed():
    """Run 26: lock older than 2h must not 409 /api/run, and must be reaped."""
    from datetime import datetime, timedelta, timezone

    from fastapi.testclient import TestClient

    from dashboard.main import app
    from swarm.orm import RunLockRow
    from swarm.run_daily import main

    init_db()
    release_lock()
    with session_scope() as session:
        session.query(RunRow).filter(RunRow.id == 26).delete()
        session.add(RunRow(id=26, status="running", current_stage="desk"))
    acquire_lock(26)
    with session_scope() as session:
        lock = session.get(RunLockRow, "daily")
        assert lock is not None
        lock.acquired_at = datetime.now(timezone.utc) - timedelta(seconds=8000)

    assert held_run_id() is None
    assert current_lock() is None
    assert locked_run_id() == 26

    client = TestClient(app)
    status = client.get("/api/status")
    assert status.status_code == 200
    assert status.json()["running"] is False

    closed = close_orphans_on_startup()
    assert closed >= 1
    assert locked_run_id() is None
    with session_scope() as session:
        row = session.get(RunRow, 26)
        assert row is not None
        assert row.status == "failed"
        assert "orphan" in (row.error or "")
        assert row.finished_at is not None

    release_lock()
    with session_scope() as session:
        session.query(RunRow).filter(RunRow.id == 26).delete()
        session.add(RunRow(id=26, status="running", current_stage="desk"))
    acquire_lock(26)
    with session_scope() as session:
        lock = session.get(RunLockRow, "daily")
        lock.acquired_at = datetime.now(timezone.utc) - timedelta(seconds=8000)
    rc = main(["--close-orphans"])
    assert rc == 0
    assert locked_run_id() is None
    with session_scope() as session:
        row = session.get(RunRow, 26)
        assert row.status == "failed"


def test_api_run_does_not_409_on_a_stale_lock(monkeypatch):
    """POST /api/run used current_lock() with no stale check — 409 forever."""
    from datetime import datetime, timedelta, timezone

    from fastapi.testclient import TestClient

    from dashboard import main as dash
    from swarm.orm import RunLockRow

    init_db()
    release_lock()
    with session_scope() as session:
        session.query(RunRow).filter(RunRow.id == 26).delete()
        session.add(RunRow(id=26, status="running", current_stage="desk"))
    acquire_lock(26)
    with session_scope() as session:
        lock = session.get(RunLockRow, "daily")
        lock.acquired_at = datetime.now(timezone.utc) - timedelta(seconds=8000)

    monkeypatch.setattr(dash, "refuse_if_over_ceiling", lambda: None)
    monkeypatch.setattr(dash, "refuse_if_cooling_down", lambda _req: None)

    class _QuietThread:
        def __init__(self, target=None, daemon=False):
            self._target = target

        def start(self):
            return None

        def is_alive(self):
            return False

    monkeypatch.setattr(dash.threading, "Thread", _QuietThread)
    client = TestClient(app := dash.app)
    res = client.post("/api/run")
    assert res.status_code == 200
    assert res.json()["started"] is True
    with session_scope() as session:
        row = session.get(RunRow, 26)
        assert row.status == "failed"
    assert locked_run_id() is None
