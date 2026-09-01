from fastapi.testclient import TestClient

from dashboard.main import app
from swarm.db import init_db


def test_health_and_empty_today():
    init_db()
    client = TestClient(app)
    health = client.get("/healthz").json()
    assert health["ok"] is True
    assert health["pgvector_installed"] is False
    assert health["dedup"] == "lexical"
    assert client.get("/health").json()["ok"] is True
    home = client.get("/")
    assert home.status_code == 200
    assert "Question Engine" in home.text
    assert "No digest yet" in home.text or "Top questions" in home.text
