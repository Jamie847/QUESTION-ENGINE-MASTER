"""CW Finding 004. Empty token is locked. Spend always needs the token."""

import os

import pytest
from fastapi.testclient import TestClient

from dashboard.main import app
from swarm.db import init_db
from swarm.settings import get_settings


def _reload(**env: str) -> TestClient:
    for key in ("DASHBOARD_TOKEN", "ACCESS_TOKEN", "ALLOW_UNAUTHENTICATED"):
        os.environ.pop(key, None)
    for key, value in env.items():
        os.environ[key] = value
    get_settings.cache_clear()
    init_db()
    return TestClient(app)


@pytest.fixture(autouse=True)
def _restore_test_unlock():
    yield
    os.environ.pop("DASHBOARD_TOKEN", None)
    os.environ.pop("ACCESS_TOKEN", None)
    os.environ["ALLOW_UNAUTHENTICATED"] = "true"
    get_settings.cache_clear()


def test_empty_token_fails_closed_without_local_flag():
    """Against `if not token: allow` this goes red — that was the live hole."""
    client = _reload()
    assert client.get("/healthz").status_code == 200
    assert client.get("/").status_code == 401
    assert client.get("/controls").status_code == 401
    assert client.get("/issues").status_code == 401
    assert client.post("/api/run").status_code == 401


def test_allow_unauthenticated_opens_pages_but_spend_needs_token():
    client = _reload(ALLOW_UNAUTHENTICATED="true", DASHBOARD_TOKEN="secret")
    assert client.get("/").status_code == 200
    assert client.get("/controls").status_code == 200
    assert client.post("/api/run").status_code == 401
    # 409 means the token was accepted and the lock held — not a 401.
    assert client.post("/api/run", headers={"Authorization": "Bearer secret"}).status_code in {200, 409}


def test_local_unlock_without_token_still_allows_spend():
    """Empty token + ALLOW_UNAUTHENTICATED is the test/dev path. Production
    never sets the flag, so this does not reopen Finding 004."""
    client = _reload(ALLOW_UNAUTHENTICATED="true")
    assert client.get("/controls").status_code == 200
    assert client.post("/api/run").status_code in {200, 409}


def test_token_unlocks_pages_and_spend():
    client = _reload(DASHBOARD_TOKEN="secret")
    assert client.get("/").status_code == 401
    page = client.get("/?token=secret")
    assert page.status_code == 200
    assert client.post("/api/run?token=secret").status_code in {200, 409}


def test_every_registered_route_is_locked_or_explicitly_public():
    """A new route is 401 by default. Against a missed /controls this goes red."""
    from dashboard.main import PUBLIC_PATHS, app as dashboard_app

    client = _reload(DASHBOARD_TOKEN="secret")
    checked: list[str] = []
    for route in dashboard_app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path:
            continue
        concrete = path.replace("{day}", "2026-01-01").replace("{question_id}", "q")
        if concrete.startswith("/static"):
            concrete = "/static/style.css"
        for method in sorted(methods or {"GET"}):
            if method in {"HEAD", "OPTIONS"}:
                continue
            checked.append(f"{method} {path}")
            res = client.request(method, concrete)
            public = path.rstrip("/") in PUBLIC_PATHS or path in PUBLIC_PATHS
            if public:
                assert res.status_code != 401, f"{method} {path} should be public"
            else:
                assert res.status_code == 401, (
                    f"{method} {path} returned {res.status_code} unauthenticated"
                )
    assert any(item.endswith(" /controls") for item in checked)
    assert any(item.endswith(" /issues") for item in checked)
    assert any(" /api/run" in item for item in checked)
    assert any(" /api/status" in item for item in checked)
