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
    "main page",
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
SKIP_IF_CONTAINS = (
    "(film)",
    "(tv series)",
    "(album)",
    "(song)",
    "(book)",
    "(novel)",
    "(video game)",
)


class WikipediaSource(SourceAdapter):
    name = "wikipedia"

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
        payload: dict | None = None
        async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
            # Top-views for "yesterday" is often unpublished for ~24h.
            for lag in (1, 2, 3):
                day = datetime.now(timezone.utc).date() - timedelta(days=lag)
                path = (
                    "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
                    f"en.wikipedia/all-access/{day:%Y}/{day:%m}/{day:%d}"
                )
                resp = await client.get(path)
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                payload = resp.json()
                break
        if not payload:
            return []
        articles = (
            ((payload.get("items") or [{}])[0].get("articles") or [])
        )
        signals: list[Signal] = []
        for art in articles:
            title = (art.get("article") or "").replace("_", " ")
            low = title.lower()
            if not title or low.startswith(SKIP_PREFIXES):
                continue
            if any(tok in low for tok in SKIP_IF_CONTAINS):
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
