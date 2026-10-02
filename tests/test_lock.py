import threading

from swarm.db import init_db, session_scope
from swarm.lock import (
    LockBusy,
    acquire_lock,
    fail_unlocked_running_runs,
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
