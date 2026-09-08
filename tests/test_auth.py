"""WO-005. Open by default. Auth is a flag, not the posture."""

import logging
import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from dashboard.main import PUBLIC_PATHS, app
from dashboard.run_limits import reset_for_tests
from swarm.db import init_db, session_scope
from swarm.lock import acquire_lock, release_lock
from swarm.orm import RunRow
from swarm.settings import get_settings

_ENV_KEYS = (
    "DASHBOARD_TOKEN",
    "ACCESS_TOKEN",
    "ALLOW_UNAUTHENTICATED",
    "DASHBOARD_AUTH",
    "MAX_RUNS_PER_DAY",
    "RUN_COOLDOWN_SECONDS",
)


def _reload(**env: str) -> TestClient:
    for key in _ENV_KEYS:
        os.environ.pop(key, None)
    os.environ["DASHBOARD_AUTH"] = "off"
    os.environ["MAX_RUNS_PER_DAY"] = "1000"
    os.environ["RUN_COOLDOWN_SECONDS"] = "0"
    for key, value in env.items():
        os.environ[key] = value
    get_settings.cache_clear()
    reset_for_tests()
    init_db()
    release_lock("daily")
    release_lock("correspondent")
    return TestClient(app)


@pytest.fixture(autouse=True)
def _restore_open_default():
    yield
    for key in _ENV_KEYS:
        os.environ.pop(key, None)
    os.environ["DASHBOARD_AUTH"] = "off"
    os.environ["MAX_RUNS_PER_DAY"] = "1000"
    os.environ["RUN_COOLDOWN_SECONDS"] = "0"
    get_settings.cache_clear()
    reset_for_tests()


def _iter_routes():
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path:
            continue
        concrete = (
            path.replace("{day}", "2026-01-01")
            .replace("{question_id}", "q")
            .replace("{run_id}", "1")
        )
        if concrete.startswith("/static"):
            concrete = "/static/style.css"
        for method in sorted(methods or {"GET"}):
            if method in {"HEAD", "OPTIONS"}:
                continue
            yield method, path, concrete


def test_every_route_serves_without_credentials():
    """Against deny-by-default this goes red: open is the intended posture."""
    client = _reload()
    acquire_lock(1, name="daily")
    acquire_lock(1, name="correspondent")
    try:
        checked: list[str] = []
        for method, path, concrete in _iter_routes():
            checked.append(f"{method} {path}")
            res = client.request(method, concrete)
            assert res.status_code != 401, f"{method} {path} returned 401 with no credentials"
            assert "This digest is locked" not in res.text
        assert any(item.endswith(" /controls") for item in checked)
        assert any(item.endswith(" /issues") for item in checked)
        assert any(" /api/run" in item for item in checked)
    finally:
        release_lock("daily")
        release_lock("correspondent")


def test_auth_flag_restores_gate_and_query_beats_stale_cookie():
    """A stale cookie used to win over ?token= and lock the Operator out."""
    client = _reload(DASHBOARD_AUTH="on", DASHBOARD_TOKEN="secret")
    assert client.get("/healthz").status_code == 200
    assert client.get("/").status_code == 401
    assert client.get("/controls").status_code == 401
    assert client.get("/issues").status_code == 401
    assert client.post("/api/run").status_code == 401
    assert "This digest is locked" not in client.get("/").text

    client.cookies.set("access_token", "stale-wrong-value")
    assert client.get("/").status_code == 401
    page = client.get("/?token=secret")
    assert page.status_code == 200
    assert "Question Engine" in page.text
    acquire_lock(9, name="daily")
    try:
        # 409 means the token was accepted. 401 would mean the stale cookie won.
        assert client.post("/api/run?token=secret").status_code == 409
    finally:
        release_lock("daily")


def test_auth_flag_enumerates_locked_routes():
    client = _reload(DASHBOARD_AUTH="on", DASHBOARD_TOKEN="secret")
    for method, path, concrete in _iter_routes():
        res = client.request(method, concrete)
        public = path.rstrip("/") in PUBLIC_PATHS or path in PUBLIC_PATHS
        if public:
            assert res.status_code != 401, f"{method} {path} should stay public"
        else:
            assert res.status_code == 401, (
                f"{method} {path} returned {res.status_code} unauthenticated"
            )


def test_daily_ceiling_refuses_and_does_not_call_model(caplog):
    """Against an uncapped POST /api/run the sixth call would start a swarm."""
    client = _reload(MAX_RUNS_PER_DAY="2")
    with session_scope() as session:
        for _ in range(2):
            session.add(
                RunRow(
                    status="completed",
                    budget_usd=5.0,
                    started_at=datetime.now(timezone.utc),
                )
            )
    with patch("swarm.run_daily.main") as mock_main:
        with caplog.at_level(logging.ERROR, logger="dashboard"):
            res = client.post("/api/run")
    assert res.status_code == 429
    assert "ceiling" in res.text.lower()
    mock_main.assert_not_called()
    assert any("MAX_RUNS_PER_DAY" in rec.message for rec in caplog.records)


def test_controls_hides_provider_billing_text(caplog):
    """Against verbatim run.error this page leaked billing state."""
    init_db()
    with session_scope() as session:
        session.add(
            RunRow(
                status="failed",
                current_stage="scout",
                error=(
                    "BadRequestError: Your credit balance is too low. "
                    "request_id=req_011CefcFvZ9JZAaxnds11B8T"
                ),
                budget_usd=5.0,
                started_at=datetime.now(timezone.utc),
            )
        )
    client = _reload()
    with caplog.at_level(logging.INFO, logger="dashboard"):
        page = client.get("/controls")
    assert page.status_code == 200
    low = page.text.lower()
    assert "credit balance" not in low
    assert "too low" not in low
    assert "req_011CefcFvZ9JZAaxnds11B8T" not in page.text
    assert "badrequesterror" not in low
    assert any("credit balance" in rec.message.lower() for rec in caplog.records)
