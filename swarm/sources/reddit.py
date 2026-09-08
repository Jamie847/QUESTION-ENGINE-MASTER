from __future__ import annotations

import httpx

from swarm.config import verticals
from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.routing import hint_verticals


class RedditSource(SourceAdapter):
    name = "reddit"

    def enabled(self) -> bool:
        return True

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        subs: list[str] = []
        for v in verticals():
            subs.extend(v.get("reddit_subs") or [])
        seen_subs: list[str] = []
        for sub in subs:
            if sub not in seen_subs:
                seen_subs.append(sub)

        headers = {
            "User-Agent": settings.reddit_user_agent,
            "Accept": "application/json",
        }
        token = await _oauth_token(settings, headers)
        if token:
            headers["Authorization"] = f"Bearer {token}"
            hosts = ("https://oauth.reddit.com",)
        else:
            hosts = ("https://www.reddit.com", "https://old.reddit.com")

        signals: list[Signal] = []
        blocked = 0
        fetched_empty = 0
        async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
            for sub in seen_subs:
                path = f"/r/{sub}/hot.json?limit=12" if not token else f"/r/{sub}/hot?limit=12"
                got = None
                for host in hosts:
                    try:
                        resp = await client.get(f"{host}{path}")
                        if resp.status_code in {401, 403, 429}:
                            continue
                        resp.raise_for_status()
                        got = resp.json()
                        break
                    except (httpx.HTTPError, ValueError):
                        continue
                if got is None:
                    blocked += 1
                    continue
                children = (got.get("data") or {}).get("children") or []
                before = len(signals)
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
                if len(signals) == before:
                    fetched_empty += 1

        if not signals:
            hint = (
                "set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET"
                if not token
                else "OAuth returned no posts"
            )
            raise RuntimeError(
                f"reddit returned zero posts ({blocked} blocked, "
                f"{fetched_empty} empty). {hint}"
            )
        return signals


async def _oauth_token(settings, headers: dict[str, str]) -> str:
    cid = (settings.reddit_client_id or "").strip()
    secret = (settings.reddit_client_secret or "").strip()
    if not cid or not secret:
        return ""
    async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
        resp = await client.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(cid, secret),
            data={"grant_type": "client_credentials"},
        )
        resp.raise_for_status()
        token = (resp.json() or {}).get("access_token") or ""
        if not token:
            raise RuntimeError("reddit OAuth returned no access_token")
        return str(token)


def _sub_vertical(sub: str) -> list[str]:
    sub_l = sub.lower()
    for v in verticals():
        for listed in v.get("reddit_subs") or []:
            if listed.lower() == sub_l:
                return [v["id"]]
    return []
