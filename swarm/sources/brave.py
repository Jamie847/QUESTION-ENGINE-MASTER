from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from swarm.config import verticals
from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.routing import hint_verticals
from swarm.sources.snippets import clip_snippet

NEWS_URL = "https://api.search.brave.com/res/v1/news/search"
WEB_URL = "https://api.search.brave.com/res/v1/web/search"


def extract_brave_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Brave News returns ``results`` as a list. Brave Web nests them
    under ``web.results`` (and sometimes ``news.results``). Either shape
    is fine; a list must never be treated as a dict."""
    if not isinstance(payload, dict):
        return []
    for key in ("results", "news", "web"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            inner = value.get("results")
            if isinstance(inner, list):
                return [item for item in inner if isinstance(item, dict)]
    return []


def retry_wait_seconds(resp: httpx.Response, default: float) -> float:
    raw = resp.headers.get("X-RateLimit-Reset") or resp.headers.get("Retry-After") or ""
    first = str(raw).split(",")[0].strip()
    try:
        return max(default, float(first))
    except ValueError:
        return default


class BraveSource(SourceAdapter):
    name = "brave"
    timeout_s = 90

    def __init__(self) -> None:
        self.rate_limited_queries: list[str] = []
        self._last_request = 0.0

    def enabled(self) -> bool:
        return bool(get_settings().brave_api_key)

    async def _pace(self) -> None:
        interval = max(0.0, get_settings().brave_min_interval_s)
        if interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < interval:
            await asyncio.sleep(interval - elapsed)
        self._last_request = time.monotonic()

    async def _request(self, client: httpx.AsyncClient, url: str, params: dict) -> httpx.Response:
        await self._pace()
        resp = await client.get(url, params=params)
        if resp.status_code != 429:
            return resp
        await asyncio.sleep(retry_wait_seconds(resp, get_settings().brave_min_interval_s))
        await self._pace()
        return await client.get(url, params=params)

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        key = settings.brave_api_key
        self.rate_limited_queries = []
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
                    params = {"q": query, "count": 8, "freshness": "pw"}
                    resp = await self._request(client, NEWS_URL, params)
                    if resp.status_code == 422:
                        resp = await self._request(
                            client, WEB_URL, {"q": query, "count": 8}
                        )
                    if resp.status_code == 429:
                        self.rate_limited_queries.append(query)
                        continue
                    resp.raise_for_status()
                    for item in extract_brave_results(resp.json()):
                        title = (item.get("title") or "").strip()
                        if not title:
                            continue
                        signals.append(
                            Signal(
                                source=self.name,
                                title=title,
                                url=item.get("url") or "",
                                snippet=clip_snippet(item.get("description") or ""),
                                score=1.2,
                                vertical_hints=hint_verticals(title, verticals()) or [v["id"]],
                                raw={"query": query, "age": item.get("age")},
                            )
                        )
        return signals
