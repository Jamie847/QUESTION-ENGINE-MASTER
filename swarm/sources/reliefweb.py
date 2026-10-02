"""ReliefWeb reports. Public API; appname identifies this swarm."""

from __future__ import annotations

from typing import Any

import httpx

from swarm.config import verticals
from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.snippets import clip_snippet

API = "https://api.reliefweb.int/v1/reports"
APPNAME = "question-engine"


def extract_reports(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, dict)]


class ReliefWebSource(SourceAdapter):
    name = "reliefweb"

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
        queries: list[tuple[str, str]] = []
        for vertical in verticals():
            for query in (vertical.get("reliefweb_queries") or [])[:2]:
                queries.append((str(query), vertical["id"]))
        if not queries:
            return []
        signals: list[Signal] = []
        async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
            for query, vertical_id in queries:
                resp = await client.get(
                    API,
                    params={
                        "appname": APPNAME,
                        "query[value]": query,
                        "limit": 10,
                        "preset": "latest",
                        "fields[include][]": ["title", "url", "body-html", "date.created"],
                    },
                )
                resp.raise_for_status()
                for item in extract_reports(resp.json()):
                    fields = item.get("fields") if isinstance(item.get("fields"), dict) else item
                    title = str((fields or {}).get("title") or "").strip()
                    url = str((fields or {}).get("url") or "")
                    if not title:
                        continue
                    snippet = clip_snippet(str((fields or {}).get("body-html") or ""))
                    signals.append(
                        Signal(
                            source=self.name,
                            title=title,
                            url=url,
                            snippet=snippet,
                            score=2.8,
                            vertical_hints=[vertical_id],
                            raw={"query": query, "id": item.get("id")},
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
