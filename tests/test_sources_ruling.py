import asyncio

import pytest

from swarm.models import SourceHealth
from swarm.settings import get_settings
from swarm.sources.federal_register import extract_documents
from swarm.sources.health import annotate_dead_sources
from swarm.sources.reddit import RedditSource


def test_reddit_zero_posts_is_an_error(monkeypatch):
    """Against a silent empty return this goes red."""
    async def empty_token(_settings, _headers):
        return ""

    monkeypatch.setattr("swarm.sources.reddit._oauth_token", empty_token)

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"children": []}}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, url):
            return FakeResp()

    monkeypatch.setattr("swarm.sources.reddit.httpx.AsyncClient", FakeClient)
    with pytest.raises(RuntimeError, match="reddit returned zero"):
        asyncio.run(RedditSource().fetch())


def test_federal_register_extracts_documents():
    payload = {
        "results": [
            {"title": "SEC extends comment period", "html_url": "https://fr.test/a"},
            {"title": "  "},
            "skip",
        ]
    }
    rows = extract_documents(payload)
    assert len(rows) == 2
    assert rows[0]["title"].startswith("SEC")


def test_dead_flag_latches_then_clears(monkeypatch):
    monkeypatch.setenv("SOURCE_DEAD_AFTER_RUNS", "3")
    get_settings.cache_clear()
    prior = [
        (12, [{"source": "reddit", "count": 0, "ok": True}]),
        (11, [{"source": "reddit", "count": 0, "ok": False}]),
    ]
    dead = annotate_dead_sources(
        [SourceHealth(source="reddit", ok=True, count=0)],
        prior,
    )
    assert dead[0].dead is True
    assert dead[0].last_ok is None

    prior_with_ok = [
        (12, [{"source": "reddit", "count": 0}]),
        (10, [{"source": "reddit", "count": 8}]),
    ]
    still = annotate_dead_sources(
        [SourceHealth(source="reddit", ok=True, count=0)],
        prior_with_ok,
    )
    assert still[0].dead is False
    assert still[0].last_ok == "run 10"

    alive = annotate_dead_sources(
        [SourceHealth(source="reddit", ok=True, count=5)],
        prior,
    )
    assert alive[0].dead is False
    assert alive[0].last_ok == "this run"
