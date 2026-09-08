"""Federal Register — primary regulatory record. No key. No synthesis."""

from __future__ import annotations

from typing import Any

import httpx

from swarm.config import verticals
from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.routing import hint_verticals


def extract_documents(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, dict)]


class FederalRegisterSource(SourceAdapter):
    name = "federal_register"

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
        queries: list[str] = []
        for v in verticals():
            for query in (v.get("search_queries") or [])[:2]:
                if query not in queries:
                    queries.append(query)
        if not queries:
            queries = ["securities", "artificial intelligence"]

        signals: list[Signal] = []
        async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
            for query in queries:
                resp = await client.get(
                    "https://www.federalregister.gov/api/v1/documents.json",
                    params={
                        "per_page": 8,
                        "order": "newest",
                        "conditions[term]": query,
                    },
                )
                resp.raise_for_status()
                for item in extract_documents(resp.json()):
                    title = (item.get("title") or "").strip()
                    if not title:
                        continue
                    url = item.get("html_url") or item.get("pdf_url") or ""
                    snippet = (item.get("abstract") or item.get("excerpts") or "")[:400]
                    if isinstance(snippet, list):
                        snippet = " ".join(str(s) for s in snippet)[:400]
                    signals.append(
                        Signal(
                            source=self.name,
                            title=title,
                            url=str(url),
                            snippet=str(snippet),
                            score=1.1,
                            vertical_hints=hint_verticals(title, verticals()),
                            raw={
                                "query": query,
                                "document_number": item.get("document_number"),
                                "type": item.get("type"),
                                "agencies": [
                                    a.get("name")
                                    for a in (item.get("agencies") or [])
                                    if isinstance(a, dict)
                                ],
                            },
                        )
                    )
        return _dedupe(signals)


def _dedupe(signals: list[Signal]) -> list[Signal]:
    seen: set[str] = set()
    out: list[Signal] = []
    for s in signals:
        key = s.url or s.title.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out
