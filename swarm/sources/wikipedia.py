from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from swarm.config import verticals
from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.routing import hint_verticals

SKIP_PREFIXES = (
    "main_page",
    "special:",
    "wikipedia:",
    "portal:",
    "file:",
    "draft:",
    "template:",
    "category:",
    "help:",
    "user:",
    "talk:",
)


class WikipediaSource(SourceAdapter):
    name = "wikipedia"

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        day = datetime.now(timezone.utc).date() - timedelta(days=1)
        path = (
            "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
            f"en.wikipedia/all-access/{day:%Y}/{day:%m}/{day:%d}"
        )
        headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
            resp = await client.get(path)
            resp.raise_for_status()
            payload = resp.json()
        articles = (
            ((payload.get("items") or [{}])[0].get("articles") or [])
        )
        signals: list[Signal] = []
        for art in articles:
            title = (art.get("article") or "").replace("_", " ")
            if not title or title.lower().startswith(SKIP_PREFIXES):
                continue
            hints = hint_verticals(title, verticals())
            if not hints:
                continue
            views = float(art.get("views") or 0)
            slug = art.get("article")
            signals.append(
                Signal(
                    source=self.name,
                    title=f"Wikipedia attention: {title}",
                    url=f"https://en.wikipedia.org/wiki/{slug}",
                    snippet=f"{int(views):,} pageviews yesterday",
                    score=views / 50_000.0,
                    vertical_hints=hints,
                    raw={"views": views, "article": slug},
                )
            )
        return signals[:40]
