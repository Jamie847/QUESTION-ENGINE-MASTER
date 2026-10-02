"""Fetch a few cited pages. Timeouts stay short so the desk cannot stall the run."""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from typing import Any, Callable

import httpx

from swarm.settings import get_settings

log = logging.getLogger("swarm.desk.pages")

PAGE_TIMEOUT_S = 12.0
PAGE_CHARS = 2000


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = False
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    parser = _Text()
    try:
        parser.feed(raw or "")
    except Exception:  # noqa: BLE001 — broken HTML still yields what we got
        return re.sub(r"\s+", " ", raw or "").strip()[:PAGE_CHARS]
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    return text[:PAGE_CHARS]


def fetch_url(url: str, *, timeout_s: float = PAGE_TIMEOUT_S) -> str:
    settings = get_settings()
    headers = {"User-Agent": settings.user_agent, "Accept": "text/html,application/xhtml+xml"}
    with httpx.Client(timeout=timeout_s, follow_redirects=True, headers=headers) as client:
        resp = client.get(url)
        resp.raise_for_status()
        ctype = (resp.headers.get("content-type") or "").lower()
        if "html" not in ctype and "xml" not in ctype and "text/" not in ctype:
            return ""
        return html_to_text(resp.text)


def read_pages(
    urls: list[str],
    *,
    fetch_fn: Callable[[str], str] | None = None,
    per_claim: int = 2,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    getter = fetch_fn or fetch_url
    for url in urls:
        cleaned = str(url or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        try:
            text = getter(cleaned) or ""
        except Exception as exc:  # noqa: BLE001 — snippet fallback
            log.warning("page fetch failed %s %s", cleaned, exc)
            text = ""
        rows.append(
            {
                "url": cleaned,
                "text": text,
                "mode": "full" if text else "snippet",
            }
        )
        if len(rows) >= per_claim:
            break
    return rows


def describe_reads(pages: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for row in pages:
        url = row.get("url") or ""
        mode = row.get("mode") or "snippet"
        if mode == "full":
            lines.append(f"read in full: {url}")
        else:
            lines.append(f"snippet: {url}")
    return lines


def check_note_from(pages: list[dict[str, Any]]) -> str:
    lines = describe_reads(pages)
    if not lines:
        return "Checked from stored snippets and search snippets — no cited pages were fetched."
    return "Checked from: " + "; ".join(lines)
