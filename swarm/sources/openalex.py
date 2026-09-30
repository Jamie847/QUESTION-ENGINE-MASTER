"""OpenAlex works. Abstracts arrive as an inverted index and are rebuilt here."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx

from swarm.config import verticals
from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.snippets import clip_snippet

API = "https://api.openalex.org/works"
PER_VERTICAL = 15


def rebuild_abstract(inverted: dict | None) -> str:
    if not isinstance(inverted, dict):
        return ""
    placed: list[tuple[int, str]] = []
    for word, indexes in inverted.items():
        if not isinstance(indexes, list):
            continue
        for index in indexes:
            try:
                placed.append((int(index), str(word)))
            except (TypeError, ValueError):
                continue
    placed.sort(key=lambda pair: pair[0])
    return " ".join(word for _, word in placed)


def parse_works(payload: Any) -> list[dict]:
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []
    rows: list[dict] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = " ".join(str(item.get("display_name") or item.get("title") or "").split())
        if not title:
            continue
        openalex_id = str(item.get("id") or "")
        doi = str(item.get("doi") or "")
        url = doi or openalex_id
        rows.append(
            {
                "title": title,
                "summary": rebuild_abstract(item.get("abstract_inverted_index")),
                "openalex_id": openalex_id,
                "doi": doi,
                "url": url,
            }
        )
    return rows


class OpenAlexSource(SourceAdapter):
    name = "openalex"

    def enabled(self) -> bool:
        return bool(get_settings().openalex_api_key)

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        key = settings.openalex_api_key
        if not key:
            return []
        since = (date.today() - timedelta(days=max(1, self.freshness_days))).isoformat()
        headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
        signals: list[Signal] = []
        async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
            for vertical in verticals():
                terms = [str(term) for term in (vertical.get("openalex_terms") or []) if term]
                if not terms:
                    continue
                resp = await client.get(
                    API,
                    params={
                        "search": " ".join(terms),
                        "filter": f"from_publication_date:{since}",
                        "per-page": PER_VERTICAL,
                        "sort": "publication_date:desc",
                        "api_key": key,
                    },
                )
                resp.raise_for_status()
                rows = parse_works(resp.json())[:PER_VERTICAL]
                total = len(rows)
                for index, row in enumerate(rows):
                    signals.append(
                        Signal(
                            source=self.name,
                            title=row["title"],
                            url=row["url"],
                            snippet=clip_snippet(row["summary"]),
                            score=float(total - index),
                            vertical_hints=[vertical["id"]],
                            raw={
                                "openalex_id": row["openalex_id"],
                                "doi": row["doi"],
                            },
                        )
                    )
        return signals
