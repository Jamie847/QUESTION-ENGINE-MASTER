"""Regulations.gov open dockets. Free api.data.gov key. Second government source."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx

from swarm.config import verticals
from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.snippets import clip_snippet

API = "https://api.regulations.gov/v4/documents"
PER_VERTICAL = 15


def parse_documents(payload: Any) -> list[dict]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    rows: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
        title = " ".join(str(attrs.get("title") or "").split())
        if not title:
            continue
        summary = attrs.get("summary") or ""
        if isinstance(summary, dict):
            summary = summary.get("content") or ""
        doc_id = str(item.get("id") or attrs.get("documentId") or "")
        docket_id = str(attrs.get("docketId") or "")
        links = item.get("links") if isinstance(item.get("links"), dict) else {}
        url = str(links.get("html") or "")
        if not url and doc_id:
            url = f"https://www.regulations.gov/document/{doc_id}"
        rows.append(
            {
                "title": title,
                "summary": str(summary or ""),
                "url": url,
                "document_id": doc_id,
                "docket_id": docket_id,
            }
        )
    return rows


class RegulationsGovSource(SourceAdapter):
    name = "regulations_gov"

    def enabled(self) -> bool:
        return bool(get_settings().regulations_gov_api_key)

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        key = settings.regulations_gov_api_key
        if not key:
            return []
        since = (date.today() - timedelta(days=max(1, self.freshness_days))).isoformat()
        headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
        signals: list[Signal] = []
        async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
            for vertical in verticals():
                queries = [str(q) for q in (vertical.get("search_queries") or []) if q][:2]
                for query in queries:
                    resp = await client.get(
                        API,
                        params={
                            "filter[searchTerm]": query,
                            "filter[postedDate][ge]": since,
                            "page[size]": PER_VERTICAL,
                            "sort": "-postedDate",
                            "api_key": key,
                        },
                    )
                    resp.raise_for_status()
                    rows = parse_documents(resp.json())[:PER_VERTICAL]
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
                                raw={
                                    "document_id": row["document_id"],
                                    "docket_id": row["docket_id"],
                                    "query": query,
                                },
                            )
                        )
        return _dedupe(signals)


def _dedupe(signals: list[Signal]) -> list[Signal]:
    seen: set[str] = set()
    out: list[Signal] = []
    for sig in signals:
        key = (sig.raw or {}).get("document_id") or sig.url or sig.title.lower()
        if key in seen:
            continue
        seen.add(str(key))
        out.append(sig)
    return out
