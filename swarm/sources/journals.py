"""Journal tables of contents. Titles and abstracts are free; articles may be paywalled."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import httpx

from swarm.config import verticals
from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.snippets import clip_snippet

PER_FEED = 15
_TAG_RE = re.compile(r"<[^>]+>")


def parse_feed_items(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    rows: list[dict] = []
    for el in root.iter():
        if not str(el.tag).endswith("item"):
            continue
        title = ""
        link = ""
        summary = ""
        guid = ""
        for child in list(el):
            tag = str(child.tag).split("}")[-1]
            text = " ".join((child.text or "").split())
            if tag == "title" and text and not title:
                title = text
            elif tag in {"description", "encoded"} and text and not summary:
                summary = text
            elif tag == "link" and not link:
                link = text or (child.attrib.get("href") or "")
            elif tag in {"identifier", "guid"} and text and not guid:
                guid = text
        if not link:
            for key, value in el.attrib.items():
                if str(key).endswith("about") and value:
                    link = value
                    break
        title = _TAG_RE.sub("", title).strip()
        summary = _TAG_RE.sub(" ", summary)
        summary = " ".join(summary.split())
        if title:
            rows.append(
                {"title": title, "url": link, "summary": summary, "guid": guid or link}
            )
    return rows


class JournalRssSource(SourceAdapter):
    name = "journals"
    timeout_s = 90

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        headers = {"User-Agent": settings.user_agent, "Accept": "application/rss+xml, application/xml"}
        feeds: list[tuple[str, str]] = []
        for vertical in verticals():
            for url in vertical.get("journal_feeds") or []:
                feeds.append((vertical["id"], str(url)))
        signals: list[Signal] = []
        async with httpx.AsyncClient(
            timeout=settings.source_timeout_s, headers=headers, follow_redirects=True
        ) as client:
            for vertical_id, url in feeds:
                resp = await client.get(url)
                resp.raise_for_status()
                rows = parse_feed_items(resp.text)[:PER_FEED]
                total = len(rows)
                for index, row in enumerate(rows):
                    signals.append(
                        Signal(
                            source=self.name,
                            title=row["title"],
                            url=row["url"],
                            snippet=clip_snippet(row["summary"]),
                            score=float(total - index),
                            vertical_hints=[vertical_id],
                            raw={"guid": row["guid"], "feed": url},
                        )
                    )
        return _dedupe(signals)


def _dedupe(signals: list[Signal]) -> list[Signal]:
    seen: set[str] = set()
    out: list[Signal] = []
    for sig in signals:
        key = sig.url or sig.title.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(sig)
    return out
