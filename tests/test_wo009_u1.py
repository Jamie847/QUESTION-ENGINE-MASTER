"""U1: Run now on Today, same endpoint, ceiling disables the control.

Red against the unfixed page: Today has no run control.
"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from dashboard.main import app
from dashboard.run_limits import median_completed_cost, run_control, stage_words
from swarm.db import init_db, session_scope
from swarm.orm import RunRow
from swarm.settings import get_settings


def test_stage_words_are_plain():
    assert stage_words("fetch") == "reading sources"
    assert stage_words("scout") == "scouting"
    assert stage_words("cross_pollinate") == "pairing topics"
    assert stage_words("smith") == "writing questions"
    assert stage_words("curate") == "judging"
    assert stage_words("archive") == "done"


def test_median_of_last_three_completed():
    init_db()
    base = datetime(2099, 6, 1, tzinfo=timezone.utc)
    with session_scope() as session:
        for i, cost in enumerate((1.0, 3.0, 2.0)):
            session.add(
                RunRow(
                    status="completed",
                    budget_usd=5,
                    cost_usd=cost,
                    finished_at=base + timedelta(days=i),
                )
            )
    assert median_completed_cost() == 2.0


def test_today_renders_run_control(monkeypatch):
    monkeypatch.setenv("MAX_RUNS_PER_DAY", "99")
    get_settings.cache_clear()
    try:
        init_db()
        page = TestClient(app).get("/")
        assert page.status_code == 200
        assert "data-run-btn" in page.text
        assert "Run now" in page.text
        assert "/api/run" in TestClient(app).get("/static/app.js").text
    finally:
        monkeypatch.delenv("MAX_RUNS_PER_DAY", raising=False)
        get_settings.cache_clear()


def test_today_run_button_disabled_at_ceiling(monkeypatch):
    monkeypatch.setenv("MAX_RUNS_PER_DAY", "1")
    get_settings.cache_clear()
    try:
        init_db()
        with session_scope() as session:
            session.add(
                RunRow(
                    status="completed",
                    budget_usd=5,
                    cost_usd=1.4,
                    started_at=datetime.now(timezone.utc),
                )
            )
        state = run_control()
        assert state["at_ceiling"] is True
        page = TestClient(app).get("/")
        assert page.status_code == 200
        assert "disabled" in page.text
        assert "Daily run ceiling reached" in page.text
    finally:
        monkeypatch.setenv("MAX_RUNS_PER_DAY", "1000")
        get_settings.cache_clear()
