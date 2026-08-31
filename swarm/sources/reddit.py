from __future__ import annotations

import httpx

from swarm.config import verticals
from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.routing import hint_verticals


class RedditSource(SourceAdapter):
    name = "reddit"

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        subs: list[str] = []
        for v in verticals():
            subs.extend(v.get("reddit_subs") or [])
        # unique, stable order
        seen_subs: list[str] = []
        for sub in subs:
            if sub not in seen_subs:
                seen_subs.append(sub)

        headers = {
            "User-Agent": settings.user_agent,
            "Accept": "application/json",
        }
        signals: list[Signal] = []
        async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
            for sub in seen_subs:
                url = f"https://www.reddit.com/r/{sub}/hot.json?limit=12"
                try:
                    resp = await client.get(url)
                    if resp.status_code in {401, 403, 429}:
                        # Datacenter IPs often get blocked. Degrade this sub, not the run.
                        continue
                    resp.raise_for_status()
                    children = (resp.json().get("data") or {}).get("children") or []
                except (httpx.HTTPError, ValueError):
                    continue
                for child in children:
                    data = child.get("data") or {}
                    title = (data.get("title") or "").strip()
                    if not title or data.get("stickied"):
                        continue
                    permalink = data.get("permalink") or ""
                    url_out = (
                        f"https://www.reddit.com{permalink}"
                        if permalink
                        else (data.get("url") or "")
                    )
                    signals.append(
                        Signal(
                            source=self.name,
                            title=title,
                            url=url_out,
                            snippet=(data.get("selftext") or "")[:400],
                            score=float(data.get("ups") or 0)
                            + float(data.get("num_comments") or 0) * 0.3,
                            vertical_hints=hint_verticals(title, verticals())
                            or _sub_vertical(sub),
                            raw={"subreddit": sub, "ups": data.get("ups")},
                        )
                    )
        return signals


def _sub_vertical(sub: str) -> list[str]:
    sub_l = sub.lower()
    for v in verticals():
        for listed in v.get("reddit_subs") or []:
            if listed.lower() == sub_l:
                return [v["id"]]
    return []
