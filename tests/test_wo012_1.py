"""WO-012.1. Each assertion is red against the unfixed tree."""

from __future__ import annotations

import inspect
import time
from types import SimpleNamespace

import httpx
import pytest

from swarm.config import verticals
from swarm.desk.classify import classify_orgs, none_found, prospects_with_links
from swarm.desk.pages import describe_reads
from swarm.settings import get_settings
from swarm.sources.cftc import cftc_params, extract_points
from swarm.sources.federal_register import (
    RECORDED_VALID_AGENCIES,
    build_fr_params,
    official_agency_slug,
)
from swarm.sources.gdelt import GDELT_MIN_INTERVAL_S, GdeltSource


def test_federal_register_request_matches_recorded_valid_agencies():
    """RED TODAY: YAML still sends bureau-of-industry-and-security (400)."""
    slugs = []
    for vertical in verticals():
        slugs.extend(str(a) for a in (vertical.get("federal_register_agencies") or []))
    assert slugs
    remapped = [official_agency_slug(s) for s in slugs]
    assert "bureau-of-industry-and-security" not in remapped
    assert "office-of-foreign-assets-control" not in remapped
    assert "industry-and-security-bureau" in remapped
    assert "foreign-assets-control-office" in remapped
    params = build_fr_params(
        "student loans",
        ["bureau-of-industry-and-security", "education-department"],
        window_days=7,
        prefer_significant=True,
    )
    agencies = [v for k, v in params if k == "conditions[agencies][]"]
    assert agencies
    assert all(a in RECORDED_VALID_AGENCIES for a in agencies)
    assert ("conditions[significant]", "1") in params
    assert ("conditions[type][]", "RULE") in params
    assert ("conditions[type][]", "PRORULE") in params


def test_gdelt_is_paced_and_names_a_lasting_429(monkeypatch):
    """RED TODAY: two queries fire with no sleep; 429 raises and drops the query."""
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    class _Resp:
        def __init__(self, status: int, url: str) -> None:
            self.status_code = status
            self.url = url
            self.text = "Please limit requests to one every 5 seconds"

        def json(self):
            return {"articles": []}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "429", request=None, response=SimpleNamespace(status_code=429)
                )

    calls: list[str] = []

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, url, params=None):
            q = (params or {}).get("query", "")
            calls.append(q)
            return _Resp(429, f"{url}?query={q}")

    monkeypatch.setattr("swarm.sources.gdelt.httpx.AsyncClient", lambda **_k: _Client())
    src = GdeltSource()
    import asyncio

    signals = asyncio.get_event_loop().run_until_complete(src.fetch())
    assert signals == []
    assert src.rate_limited_queries
    assert any("sanctions" in q or "export" in q for q in src.rate_limited_queries)
    assert GDELT_MIN_INTERVAL_S >= 5
    assert any(s >= 5 for s in sleeps) or len(calls) == 1


def test_rivals_versus_commentators():
    """RED TODAY: Duane Morris and Prentus both land in Rivals."""
    hits = [
        {
            "title": "Prentus — earnings-test compliance software",
            "snippet": "A software platform that maps program-level earnings-test failure rates.",
            "url": "https://prentus.example/earnings",
            "name": "Prentus",
        },
        {
            "title": "Duane Morris client alert",
            "snippet": "The law firm published an institutional compliance alert on the rule.",
            "url": "https://www.duanemorris.com/alerts/earnings",
            "name": "Duane Morris",
        },
    ]
    rivals, writers = classify_orgs(hits)
    rival_names = [r["name"] for r in rivals]
    writer_names = [w["name"] for w in writers]
    assert "Prentus" in rival_names
    assert "Duane Morris" in writer_names
    assert "Duane Morris" not in rival_names


def test_absence_needs_three_searches():
    """RED TODAY: rivals_phrase([], 2) already prints none found in 2 searches."""
    assert none_found(2, kind="rivals") is None
    assert none_found(3, kind="rivals") == "none found in 3 searches"


def test_prospects_carry_links():
    """RED TODAY: first_prospects is a list of bare names."""
    evidence = "Wisconsin Hospital Association filed comments. https://wha.org/earnings"
    kept = prospects_with_links(
        [
            {"name": "Wisconsin Hospital Association", "url": "https://wha.org/earnings"},
            {"name": "Acme Corp", "url": "https://acme.example"},
        ],
        evidence,
    )
    assert kept == [
        {"name": "Wisconsin Hospital Association", "url": "https://wha.org/earnings"}
    ]
    assert all(p.get("url") for p in kept)


def test_pages_read_are_labelled():
    """RED TODAY: every card says cited pages were not fetched."""
    lines = describe_reads(
        [
            {"url": "https://ed.gov/earnings", "mode": "full"},
            {"url": "https://news.example/x", "mode": "snippet"},
        ]
    )
    blob = " ".join(lines).lower()
    assert "read in full" in blob
    assert "snippet" in blob
    assert "cited pages were not fetched" not in blob


def test_desk_model_comes_from_the_environment(monkeypatch):
    """RED TODAY: desk calls use JUDGMENT_MODEL; no DESK_MODEL setting."""
    monkeypatch.setenv("DESK_MODEL", "claude-opus-5-5")
    get_settings.cache_clear()
    assert get_settings().desk_model == "claude-opus-5-5"
    import swarm.agents.desk as desk

    source = inspect.getsource(desk)
    assert "claude-" not in source
    assert "desk_model" in source


def test_cftc_query_is_newest_first_for_the_named_market():
    """RED TODAY: $order is oldest-first and there is no market $where."""
    params = cftc_params("CRUDE OIL")
    assert "DESC" in str(params.get("$order", "")).upper()
    assert "CRUDE OIL" in str(params.get("$where", "")).upper()
    old = [
        {
            "market_and_exchange_names": "WHEAT - MIDAMERICA COMMODITY EXCHANGE",
            "noncomm_positions_long_all": "100",
            "report_date_as_yyyy_mm_dd": "1986-01-15T00:00:00.000",
        }
    ]
    values, dates = extract_points(old, "CRUDE OIL")
    assert values == []
    recent = [
        {
            "market_and_exchange_names": "WTI FINANCIAL CRUDE OIL - NEW YORK MERCANTILE EXCHANGE",
            "noncomm_positions_long_all": "221000",
            "report_date_as_yyyy_mm_dd": "2026-09-22T00:00:00.000",
        },
        {
            "market_and_exchange_names": "WTI FINANCIAL CRUDE OIL - NEW YORK MERCANTILE EXCHANGE",
            "noncomm_positions_long_all": "210000",
            "report_date_as_yyyy_mm_dd": "2026-09-15T00:00:00.000",
        },
        {
            "market_and_exchange_names": "WTI FINANCIAL CRUDE OIL - NEW YORK MERCANTILE EXCHANGE",
            "noncomm_positions_long_all": "205000",
            "report_date_as_yyyy_mm_dd": "2026-09-08T00:00:00.000",
        },
    ]
    values, dates = extract_points(recent, "CRUDE OIL")
    assert values == [205000.0, 210000.0, 221000.0]
    assert dates[-1] == "2026-09-22"
