from __future__ import annotations

import httpx

from swarm.config import verticals
from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.routing import hint_verticals


class BraveSource(SourceAdapter):
    name = "brave"

    def enabled(self) -> bool:
        return bool(get_settings().brave_api_key)

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        key = settings.brave_api_key
        if not key:
            return []
        headers = {
            "User-Agent": settings.user_agent,
            "Accept": "application/json",
            "X-Subscription-Token": key,
        }
        signals: list[Signal] = []
        async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
            for v in verticals():
                for query in (v.get("search_queries") or [])[:2]:
                    resp = await client.get(
                        "https://api.search.brave.com/res/v1/news/search",
                        params={"q": query, "count": 8, "freshness": "pw"},
                    )
                    if resp.status_code == 422:
                        # news endpoint not on this plan — fall back to web
                        resp = await client.get(
                            "https://api.search.brave.com/res/v1/web/search",
                            params={"q": query, "count": 8},
                        )
                    resp.raise_for_status()
                    payload = resp.json()
                    results = (payload.get("results") or payload.get("news") or {}).get(
                        "results"
                    )
                    if results is None:
                        results = payload.get("results") or []
                    if isinstance(results, dict):
                        results = results.get("results") or []
                    for item in results:
                        title = (item.get("title") or "").strip()
                        if not title:
                            continue
                        signals.append(
                            Signal(
                                source=self.name,
                                title=title,
                                url=item.get("url") or "",
                                snippet=(item.get("description") or "")[:400],
                                score=1.2,
                                vertical_hints=hint_verticals(title, verticals()) or [v["id"]],
                                raw={"query": query, "age": item.get("age")},
                            )
                        )
        return signals
