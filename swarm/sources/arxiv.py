"""arXiv preprints. One category query per vertical, spaced to the published 3s limit."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
import xml.etree.ElementTree as ET

import httpx

from swarm.config import verticals
from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.snippets import clip_snippet

ATOM = "{http://www.w3.org/2005/Atom}"
API = "https://export.arxiv.org/api/query"
# https://info.arxiv.org/help/api/tou.html — one request every three seconds.
REQUEST_GAP_S = 3.0
PER_VERTICAL = 15


def parse_arxiv_feed(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    rows: list[dict] = []
    for entry in root.findall(f"{ATOM}entry"):
        title = _text(entry, "title")
        summary = _text(entry, "summary")
        id_url = _text(entry, "id")
        arxiv_id = id_url.rsplit("/abs/", 1)[-1] if "/abs/" in id_url else id_url.rsplit("/", 1)[-1]
        link = ""
        for el in entry.findall(f"{ATOM}link"):
            href = el.attrib.get("href") or ""
            if el.attrib.get("rel") in {None, "alternate"} and href:
                link = href
                break
        if not link and arxiv_id:
            link = f"https://arxiv.org/abs/{arxiv_id}"
        if title:
            rows.append(
                {"title": title, "summary": summary, "arxiv_id": arxiv_id, "url": link}
            )
    return rows


def _text(entry: ET.Element, name: str) -> str:
    el = entry.find(f"{ATOM}{name}")
    return " ".join((el.text or "").split()) if el is not None and el.text else ""


class ArxivSource(SourceAdapter):
    name = "arxiv"
    timeout_s = 90

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        headers = {"User-Agent": settings.user_agent, "Accept": "application/atom+xml"}
        since = date.today() - timedelta(days=max(1, self.freshness_days))
        start = since.strftime("%Y%m%d") + "0000"
        end = date.today().strftime("%Y%m%d") + "2359"
        signals: list[Signal] = []
        first = True
        async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
            for vertical in verticals():
                cats = [str(c) for c in (vertical.get("arxiv_categories") or []) if c]
                if not cats:
                    continue
                if not first:
                    await asyncio.sleep(REQUEST_GAP_S)
                first = False
                cat_query = " OR ".join(f"cat:{cat}" for cat in cats)
                query = f"({cat_query}) AND submittedDate:[{start} TO {end}]"
                resp = await client.get(
                    API,
                    params={
                        "search_query": query,
                        "sortBy": "submittedDate",
                        "sortOrder": "descending",
                        "start": 0,
                        "max_results": PER_VERTICAL,
                    },
                )
                resp.raise_for_status()
                rows = parse_arxiv_feed(resp.text)[:PER_VERTICAL]
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
                            raw={"arxiv_id": row["arxiv_id"], "query": query},
                        )
                    )
        return _dedupe(signals)


def _dedupe(signals: list[Signal]) -> list[Signal]:
    seen: set[str] = set()
    out: list[Signal] = []
    for sig in signals:
        key = (sig.raw or {}).get("arxiv_id") or sig.url or sig.title.lower()
        if key in seen:
            continue
        seen.add(str(key))
        out.append(sig)
    return out
