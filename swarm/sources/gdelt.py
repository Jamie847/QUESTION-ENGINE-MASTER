"""GDELT DOC API — global news. No key. One request every 5 seconds."""

from __future__ import annotations

import time
from typing import Any

import httpx

from swarm.config import verticals
from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.snippets import clip_snippet

API = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_MIN_INTERVAL_S = 5.5


def extract_articles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("articles") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, dict)]


def articles_to_signals(
    articles: list[dict[str, Any]], *, vertical_id: str, query: str = ""
) -> list[Signal]:
    signals: list[Signal] = []
    for item in articles:
        title = (item.get("title") or "").strip()
        url = str(item.get("url") or "")
        if not title or not url:
            continue
        signals.append(
            Signal(
                source="gdelt",
                title=title,
                url=url,
                snippet=clip_snippet(item.get("seendate") or item.get("domain") or ""),
                score=3.2,
                vertical_hints=[vertical_id],
                raw={"query": query, "domain": item.get("domain")},
            )
        )
    return signals


def combine_queries(queries: list[str]) -> list[str]:
    cleaned = [str(q).strip() for q in queries if str(q).strip()]
    if len(cleaned) <= 1:
        return cleaned
    return ["(" + ") OR (".join(cleaned) + ")"]


class GdeltSource(SourceAdapter):
    name = "gdelt"

    def __init__(self) -> None:
        self.rate_limited_queries: list[str] = []

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
        queries: list[tuple[str, str]] = []
        for vertical in verticals():
            combined = combine_queries(
                [str(q) for q in (vertical.get("gdelt_queries") or [])[:2]]
            )
            for query in combined:
                queries.append((query, vertical["id"]))
        signals: list[Signal] = []
        gap = max(GDELT_MIN_INTERVAL_S, float(getattr(settings, "gdelt_min_interval_s", 5.5)))
        last = 0.0
        async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
            for query, vertical_id in queries:
                wait = gap - (time.monotonic() - last) if last else 0.0
                if wait > 0:
                    time.sleep(wait)
                rows, limited = await _get_articles(client, query)
                last = time.monotonic()
                if limited:
                    self.rate_limited_queries.append(query)
                    continue
                signals.extend(
                    articles_to_signals(rows, vertical_id=vertical_id, query=query)
                )
        return _dedupe(signals)


async def _get_articles(
    client: httpx.AsyncClient, query: str
) -> tuple[list[dict[str, Any]], bool]:
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": 15,
        "timespan": "3d",
    }
    for attempt in range(2):
        resp = await client.get(API, params=params)
        if resp.status_code == 429:
            if attempt == 0:
                time.sleep(6)
                continue
            return [], True
        resp.raise_for_status()
        payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(payload, dict):
            # GDELT sometimes 200s a throttle sentence
            text = (resp.text or "").lower()
            if "one every 5 seconds" in text or "429" in text:
                if attempt == 0:
                    time.sleep(6)
                    continue
                return [], True
            return [], False
        return extract_articles(payload), False
    return [], True


def _dedupe(signals: list[Signal]) -> list[Signal]:
    seen: set[str] = set()
    out: list[Signal] = []
    for sig in signals:
        key = sig.url or sig.title.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(sig)
    return out
