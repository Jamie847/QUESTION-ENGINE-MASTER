from __future__ import annotations

import httpx

from swarm.config import verticals
from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.routing import contains_keyword, hint_verticals


class HackerNewsSource(SourceAdapter):
    name = "hacker_news"

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        headers = {"User-Agent": settings.user_agent}
        signals: list[Signal] = []
        async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
            for path, extra_score in (
                ("search?tags=front_page", 1.0),
                ("search_by_date?tags=story&hitsPerPage=30", 0.7),
            ):
                url = f"https://hn.algolia.com/api/v1/{path}"
                resp = await client.get(url)
                resp.raise_for_status()
                hits = resp.json().get("hits") or []
                for hit in hits:
                    title = (hit.get("title") or "").strip()
                    if not title:
                        continue
                    points = float(hit.get("points") or 0)
                    comments = float(hit.get("num_comments") or 0)
                    object_id = hit.get("objectID")
                    story_url = hit.get("url") or (
                        f"https://news.ycombinator.com/item?id={object_id}" if object_id else ""
                    )
                    hints = hint_verticals(title, verticals())
                    if not hints and not _mentions_any_keyword(title):
                        # Keep a few untagged front-page stories as culture/tech spillover.
                        if extra_score < 1.0:
                            continue
                    signals.append(
                        Signal(
                            source=self.name,
                            title=title,
                            url=story_url,
                            snippet=(hit.get("story_text") or "")[:400],
                            score=(points + comments * 0.4) * extra_score,
                            vertical_hints=hints,
                            raw={"points": points, "comments": comments, "objectID": object_id},
                        )
                    )
        return _dedupe(signals)


def _mentions_any_keyword(title: str) -> bool:
    for v in verticals():
        for kw in v.get("hn_keywords") or []:
            if contains_keyword(title, kw):
                return True
    return False


def _dedupe(signals: list[Signal]) -> list[Signal]:
    seen: set[str] = set()
    out: list[Signal] = []
    for s in signals:
        key = s.title.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out
