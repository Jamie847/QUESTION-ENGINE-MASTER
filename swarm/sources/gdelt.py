"""GDELT DOC API — global news. No key."""

from __future__ import annotations

from typing import Any

import httpx

from swarm.config import verticals
from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.snippets import clip_snippet

API = "https://api.gdeltproject.org/api/v2/doc/doc"


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


class GdeltSource(SourceAdapter):
    name = "gdelt"

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
        queries: list[tuple[str, str]] = []
        for vertical in verticals():
            for query in (vertical.get("gdelt_queries") or [])[:2]:
                queries.append((str(query), vertical["id"]))
        signals: list[Signal] = []
        async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
            for query, vertical_id in queries:
                resp = await client.get(
                    API,
                    params={
                        "query": query,
                        "mode": "ArtList",
                        "format": "json",
                        "maxrecords": 15,
                        "timespan": "3d",
                    },
                )
                resp.raise_for_status()
                signals.extend(
                    articles_to_signals(
                        extract_articles(resp.json()),
                        vertical_id=vertical_id,
                        query=query,
                    )
                )
        return _dedupe(signals)


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
