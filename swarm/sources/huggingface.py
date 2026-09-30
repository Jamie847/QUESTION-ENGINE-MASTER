"""Hugging Face daily papers — AI only, the papers practitioners upvoted today."""

from __future__ import annotations

from typing import Any

import httpx

from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.snippets import clip_snippet

API = "https://huggingface.co/api/daily_papers"
PER_VERTICAL = 15


def parse_daily_papers(payload: Any) -> list[dict]:
    if not isinstance(payload, list):
        return []
    rows: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        paper = item.get("paper") if isinstance(item.get("paper"), dict) else {}
        title = str(paper.get("title") or item.get("title") or "").strip()
        summary = paper.get("summary") or item.get("summary") or ""
        arxiv_id = str(paper.get("id") or "").strip()
        if not title:
            continue
        rows.append(
            {
                "title": " ".join(title.split()),
                "summary": summary,
                "arxiv_id": arxiv_id,
                "url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "",
                "upvotes": int(paper.get("upvotes") or 0),
            }
        )
    return rows


class HuggingFacePapersSource(SourceAdapter):
    name = "huggingface"

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
            resp = await client.get(API, params={"limit": PER_VERTICAL})
            resp.raise_for_status()
            rows = parse_daily_papers(resp.json())[:PER_VERTICAL]
        return [
            Signal(
                source=self.name,
                title=row["title"],
                url=row["url"],
                snippet=clip_snippet(row["summary"]),
                score=float(row["upvotes"]),
                vertical_hints=["ai"],
                raw={"arxiv_id": row["arxiv_id"]},
            )
            for row in rows
        ]
