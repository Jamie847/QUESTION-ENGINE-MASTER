"""SAM.gov contract opportunities.

A non-federal personal key is 10 requests / 24 hours (GSA public-API table).
Five verticals is one call each, which fits a single run and does not fit a
second run the same day. USAspending was not substituted: one call per
vertical per run is inside that limit.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx

from swarm.config import verticals
from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.snippets import clip_snippet

API = "https://api.sam.gov/opportunities/v2/search"
PER_VERTICAL = 15


def parse_opportunities(payload: Any) -> list[dict]:
    rows_in = None
    if isinstance(payload, dict):
        rows_in = payload.get("opportunitiesData") or payload.get("data")
    if not isinstance(rows_in, list):
        return []
    rows: list[dict] = []
    for item in rows_in:
        if not isinstance(item, dict):
            continue
        title = " ".join(str(item.get("title") or "").split())
        if not title:
            continue
        notice_id = str(item.get("noticeId") or item.get("notice_id") or "")
        url = str(item.get("uiLink") or "")
        if not url and notice_id:
            url = f"https://sam.gov/opp/{notice_id}/view"
        rows.append(
            {
                "title": title,
                "summary": str(item.get("description") or ""),
                "url": url,
                "notice_id": notice_id,
            }
        )
    return rows


class SamGovSource(SourceAdapter):
    name = "sam_gov"

    def enabled(self) -> bool:
        return bool(get_settings().sam_gov_api_key)

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        key = settings.sam_gov_api_key
        if not key:
            return []
        start = date.today() - timedelta(days=max(1, self.freshness_days))
        headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
        signals: list[Signal] = []
        async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
            for vertical in verticals():
                keywords = [str(k) for k in (vertical.get("sam_keywords") or []) if k]
                naics = [str(n) for n in (vertical.get("sam_naics") or []) if n]
                if not keywords and not naics:
                    continue
                params: dict[str, str] = {
                    "api_key": key,
                    "postedFrom": start.strftime("%m/%d/%Y"),
                    "postedTo": date.today().strftime("%m/%d/%Y"),
                    "ptype": "o,p,k,r,s",
                    "limit": str(PER_VERTICAL),
                    "offset": "0",
                }
                if keywords:
                    params["title"] = keywords[0]
                if naics:
                    params["ncode"] = naics[0]
                resp = await client.get(API, params=params)
                resp.raise_for_status()
                rows = parse_opportunities(resp.json())[:PER_VERTICAL]
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
                            raw={"notice_id": row["notice_id"], "query": params.get("title", "")},
                        )
                    )
        return signals
