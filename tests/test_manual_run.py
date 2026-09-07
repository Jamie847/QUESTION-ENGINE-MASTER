import time

from fastapi.testclient import TestClient
from sqlalchemy import select

from dashboard.main import app
from swarm.db import init_db, session_scope
from swarm.lock import release_lock
from swarm.orm import DigestRow, RunRow
from swarm.run_daily import main as swarm_main


def _digest_for_latest_run():
    with session_scope() as session:
        run = session.scalar(select(RunRow).order_by(RunRow.id.desc()))
        if not run:
            return None
        return session.scalar(select(DigestRow).where(DigestRow.run_id == run.id))


def test_cli_path_writes_a_digest_row():
    """Cron Trigger Run is this same entrypoint. Digest-row assertion first."""
    init_db()
    release_lock()
    assert swarm_main(["--force"]) == 0
    row = _digest_for_latest_run()
    assert row is not None
    assert row.curated_count >= 0
    assert any(str(w).startswith("writer_ok_calls=") for w in (row.warnings or []))


def test_controls_post_writes_a_digest_row():
    """Dashboard POST /api/run. Digest-row assertion first."""
    init_db()
    release_lock()
    client = TestClient(app)
    res = client.post("/api/run", params={"force": "true"})
    assert res.status_code == 200
    deadline = time.time() + 90
    row = None
    while time.time() < deadline:
        row = _digest_for_latest_run()
        if row is not None and any(
            str(w).startswith("writer_ok_calls=") for w in (row.warnings or [])
        ):
            break
        time.sleep(0.4)
    assert row is not None
    assert any(str(w).startswith("writer_ok_calls=") for w in (row.warnings or []))
