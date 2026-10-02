"""Federal Register — primary regulatory record. No key. No synthesis."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import httpx

from swarm.config import verticals
from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.routing import hint_verticals
from swarm.sources.snippets import clip_snippet

API = "https://www.federalregister.gov/api/v1/documents.json"
RULE_TYPES = ("RULE", "PRORULE")
HOUSEKEEPING_RE = re.compile(
    r"airworthiness directives?|"
    r"advisory committee.{0,80}renewal|"
    r"request for nominations for (individuals|advisory)",
    re.I,
)


def extract_documents(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, dict)]


def is_housekeeping(title: str, doc_type: str = "") -> bool:
    """ADs publish as rules; committee renewals publish as notices. Drop both."""
    blob = f"{title} {doc_type}"
    return bool(HOUSEKEEPING_RE.search(blob))


def keep_document(item: dict[str, Any]) -> bool:
    title = (item.get("title") or "").strip()
    if not title:
        return False
    doc_type = str(item.get("type") or "")
    if is_housekeeping(title, doc_type):
        return False
    kind = doc_type.replace(" ", "").lower()
    if kind and kind not in {"rule", "proposedrule"}:
        return False
    return True


class FederalRegisterSource(SourceAdapter):
    name = "federal_register"

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
        jobs: list[tuple[str, list[str], str]] = []
        for vertical in verticals():
            agencies = [str(a) for a in (vertical.get("federal_register_agencies") or []) if a]
            for query in (vertical.get("search_queries") or [])[:2]:
                jobs.append((query, agencies, vertical["id"]))
        if not jobs:
            jobs = [("securities", [], "business"), ("artificial intelligence", [], "ai")]

        signals: list[Signal] = []
        window = max(1, self.freshness_days)
        async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
            for query, agencies, vertical_id in jobs:
                rows = await _search(
                    client, query, agencies, window, prefer_significant=True
                )
                if len(rows) < 3:
                    extra = await _search(
                        client, query, agencies, window, prefer_significant=False
                    )
                    seen = {item.get("document_number") for item in rows}
                    rows.extend(
                        item
                        for item in extra
                        if item.get("document_number") not in seen
                    )
                for item in rows:
                    if not keep_document(item):
                        continue
                    title = (item.get("title") or "").strip()
                    url = item.get("html_url") or item.get("pdf_url") or ""
                    snippet = clip_snippet(item.get("abstract") or item.get("excerpts") or "")
                    hints = hint_verticals(title, verticals())
                    if vertical_id and vertical_id not in hints:
                        hints = [vertical_id, *hints]
                    signals.append(
                        Signal(
                            source=self.name,
                            title=title,
                            url=str(url),
                            snippet=snippet,
                            score=1.1,
                            vertical_hints=hints,
                            raw={
                                "query": query,
                                "document_number": item.get("document_number"),
                                "type": item.get("type"),
                                "agencies": [
                                    a.get("name")
                                    for a in (item.get("agencies") or [])
                                    if isinstance(a, dict)
                                ],
                                "significant": item.get("significant"),
                            },
                        )
                    )
        return _dedupe(signals)


async def _search(
    client: httpx.AsyncClient,
    query: str,
    agencies: list[str],
    window_days: int,
    *,
    prefer_significant: bool,
) -> list[dict[str, Any]]:
    params: list[tuple[str, str]] = [
        ("per_page", "8"),
        ("order", "newest"),
        ("conditions[term]", query),
        (
            "conditions[publication_date][gte]",
            (date.today() - timedelta(days=max(1, window_days))).isoformat(),
        ),
        ("conditions[type][]", "RULE"),
        ("conditions[type][]", "PRORULE"),
    ]
    if prefer_significant:
        params.append(("conditions[significant]", "1"))
    for slug in agencies:
        params.append(("conditions[agencies][]", slug))
    resp = await client.get(API, params=params)
    resp.raise_for_status()
    return extract_documents(resp.json())


def _dedupe(signals: list[Signal]) -> list[Signal]:
    seen: set[str] = set()
    out: list[Signal] = []
    for s in signals:
        key = s.url or s.title.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out
