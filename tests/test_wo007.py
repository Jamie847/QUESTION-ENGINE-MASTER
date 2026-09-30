"""WO-007 sources. Each test names the assertion that is red against unfixed code."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from swarm.agents.scout import signals_for_vertical
from swarm.config import verticals
from swarm.freshness import freshness_window_days
from swarm.models import Signal, SourceHealth
from swarm.settings import get_settings
from swarm.sources.arxiv import parse_arxiv_feed
from swarm.sources.base import collect_signals
from swarm.sources.health import annotate_dead_sources
from swarm.sources.huggingface import parse_daily_papers
from swarm.sources.journals import parse_feed_items
from swarm.sources.openalex import parse_works, rebuild_abstract
from swarm.sources.reddit import RedditSource
from swarm.sources.registry import build_sources, missing_keys
from swarm.sources.regulations import parse_documents
from swarm.sources.routing import hint_verticals
from swarm.sources.sam_gov import parse_opportunities
from swarm.sources.snippets import SNIPPET_STORE_CHARS, clip_snippet

FIXTURES = Path(__file__).resolve().parent / "fixtures"
OPERATOR_REDDIT = (
    "Operator decision 2026-09-30: dropped. Not a defect; do not re-enable without asking him."
)
EXPECTED_ABSTRACT = "Quantum-inspired Machine Learning (QiML) is a burgeoning field"


def test_s2_reddit_is_off_and_not_fetched(monkeypatch):
    """Red against a build that still calls RedditSource.fetch and counts the miss as dead."""
    yaml_text = Path("swarm/config/sources.yaml").read_text(encoding="utf-8")
    assert OPERATOR_REDDIT in yaml_text
    reddit = next(src for src in build_sources() if src.name == "reddit")
    assert reddit.availability() == "off"

    async def boom(self):
        raise AssertionError("disabled reddit was fetched")

    monkeypatch.setattr(RedditSource, "fetch", boom)
    items, health = asyncio.run(collect_signals([reddit]))
    assert items == []
    assert health[0].error == "off"
    prior = [
        (n, [{"source": "reddit", "count": 0, "ok": True, "error": "off"}])
        for n in range(12, 0, -1)
    ]
    marked = annotate_dead_sources(
        [SourceHealth(source="reddit", ok=True, count=0, error="off")],
        prior,
    )
    assert marked[0].dead is False


def test_s2_brave_names_the_query_that_stayed_429(monkeypatch):
    """Red against swallowing a 429 and leaving Health and Business with zero Brave rows unnamed."""
    monkeypatch.setenv("BRAVE_API_KEY", "test-brave")
    monkeypatch.setenv("BRAVE_MIN_INTERVAL_S", "0")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "swarm.sources.brave.verticals",
        lambda: [
            {
                "id": "ai",
                "search_queries": ["first query", "second query"],
                "keywords": [],
                "hn_keywords": [],
            }
        ],
    )

    class FakeResp:
        def __init__(self, status: int):
            self.status_code = status
            self.headers = {"Retry-After": "0"}

        def json(self):
            return {
                "results": [
                    {
                        "title": "A first result about a named filing",
                        "url": "https://ex.test/a",
                        "description": "snippet",
                    }
                ]
            }

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params=None):
            if (params or {}).get("q") == "second query":
                return FakeResp(429)
            return FakeResp(200)

    monkeypatch.setattr("swarm.sources.brave.httpx.AsyncClient", FakeClient)
    from swarm.sources.brave import BraveSource

    src = BraveSource()
    src._config_enabled = True
    src._key_attr = "brave_api_key"
    _items, health = asyncio.run(collect_signals([src]))
    assert health[0].error and "second query" in health[0].error
    assert "second query" in health[0].rate_limited
    get_settings.cache_clear()


def test_s2_openalex_missing_key_is_needs_key_and_never_dead(monkeypatch):
    """Red against treating a missing OpenAlex key as a failed fetch that can go dead."""
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    get_settings.cache_clear()
    src = next(row for row in build_sources() if row.name == "openalex")
    assert src.availability() == "needs key"
    prior = [
        (n, [{"source": "openalex", "count": 0, "ok": True, "error": "needs key"}])
        for n in range(10, 0, -1)
    ]
    marked = annotate_dead_sources(
        [SourceHealth(source="openalex", ok=True, count=0, error="needs key")],
        prior,
    )
    assert marked[0].dead is False
    assert "openalex" in missing_keys()
    get_settings.cache_clear()


def test_s2_freshness_window_clamps_to_one_and_seven_days():
    """Red against a fixed 1-day lookback when the last archive was 10 days ago."""
    now = datetime(2026, 9, 30, tzinfo=timezone.utc)
    assert freshness_window_days(now - timedelta(days=10), now) == 7
    assert freshness_window_days(now - timedelta(hours=2), now) == 1
    assert freshness_window_days(None, now) == 1


def test_s3_targeted_signal_reaches_the_science_scout_without_a_keyword():
    """Red against hint_verticals dropping a quant-ph paper whose title has no science keyword."""
    title = "A named instrument recorded 4.1 units on 2026-03-02"
    assert hint_verticals(title, verticals()) == []
    paper = Signal(
        source="arxiv",
        title=title,
        url="https://arxiv.org/abs/2609.00001",
        snippet="Recorded at a facility.",
        score=3.0,
        vertical_hints=["science"],
        raw={"arxiv_id": "2609.00001"},
    )
    seen = signals_for_vertical("science", [paper])
    assert any(sig.raw.get("arxiv_id") == "2609.00001" for sig, _rank in seen)


def test_s3_adapters_parse_fixtures_with_snippet_and_source_id():
    """Red against a parser that drops the snippet or the source's own id."""
    arxiv_rows = parse_arxiv_feed((FIXTURES / "arxiv_atom.xml").read_text(encoding="utf-8"))
    assert arxiv_rows[0]["summary"]
    assert arxiv_rows[0]["arxiv_id"] == "2609.00001v1"
    assert clip_snippet(arxiv_rows[0]["summary"])

    hf_rows = parse_daily_papers(json.loads((FIXTURES / "huggingface_daily.json").read_text()))
    assert hf_rows[0]["summary"]
    assert hf_rows[0]["arxiv_id"] == "2609.36322"
    assert len(clip_snippet("x" * 2500)) == SNIPPET_STORE_CHARS

    journal_rows = parse_feed_items((FIXTURES / "journal_rss10.xml").read_text(encoding="utf-8"))
    assert journal_rows[0]["summary"]
    assert journal_rows[0]["guid"] == "doi:10.1000/example.1"

    works = parse_works(json.loads((FIXTURES / "openalex_works.json").read_text()))
    assert works[0]["summary"] == EXPECTED_ABSTRACT
    assert works[0]["openalex_id"] == "https://openalex.org/W4386114105"
    assert works[0]["doi"] == "https://doi.org/10.1016/j.cosrev.2026.101072"
    inverted = json.loads((FIXTURES / "openalex_works.json").read_text())["results"][0][
        "abstract_inverted_index"
    ]
    assert rebuild_abstract(inverted) == EXPECTED_ABSTRACT

    docs = parse_documents(json.loads((FIXTURES / "regulations_documents.json").read_text()))
    assert docs[0]["summary"]
    assert docs[0]["document_id"] == "FDA-2026-0001"
    assert docs[0]["docket_id"] == "FDA-2026-N-1"

    notices = parse_opportunities(json.loads((FIXTURES / "sam_opportunities.json").read_text()))
    assert notices[0]["summary"]
    assert notices[0]["notice_id"] == "abc123notice"


def test_s4_science_and_education_are_phase_one_with_draft_queries():
    """Red against a loader that still exposes only ai, health, and business."""
    ids = [row["id"] for row in verticals()]
    assert ids == ["ai", "health", "business", "science", "education"]
    text = Path("swarm/config/verticals.yaml").read_text(encoding="utf-8")
    assert "Operator added 2026-09-30" in text
    assert "# draft — tune after first run" in text
    for row in verticals():
        assert row.get("arxiv_categories"), row["id"]
        assert row.get("openalex_terms"), row["id"]
        assert "journal_feeds" in row
        assert row.get("sam_keywords"), row["id"]
    science = next(row for row in verticals() if row["id"] == "science")
    assert "quant-ph" in science["arxiv_categories"]


def test_s1_scout_block_includes_a_trimmed_snippet():
    """Red against a scout line that is title, source, and score with no snippet."""
    snippet = "NIST published 42 results on 2026-01-02. " + ("detail " * 400)
    sig = Signal(
        source="arxiv",
        title="Paper about a named agency",
        url="https://arxiv.org/abs/x",
        snippet=snippet,
        score=99.0,
    )
    block = format_signal_block([(sig, 1)], snippet_chars=800)
    assert block.startswith("- S1 (arxiv, rank 1)")
    assert "NIST published 42" in block
    assert "score=" not in block
    body = block.split("\n")[1].strip()
    assert len(body) == 800
