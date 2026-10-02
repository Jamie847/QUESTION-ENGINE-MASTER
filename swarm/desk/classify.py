"""Split vendors from commentators. Prospects keep the link they were found on."""

from __future__ import annotations

import re
from typing import Any

WRITER_MARKERS = re.compile(
    r"\b(law firm|llp|attorney|counsel|think[- ]tank|institute|"
    r"urban institute|consultancy|consulting|client alert|"
    r"commentary|newspaper|magazine|op[- ]ed)\b",
    re.I,
)
VENDOR_MARKERS = re.compile(
    r"\b(software|platform|saas|vendor|product|tool|app|marketplace)\b",
    re.I,
)
GIANTS = {
    "openai",
    "synopsys",
    "google",
    "microsoft",
    "amazon",
    "apple",
    "meta",
    "nvidia",
    "ibm",
    "oracle",
    "salesforce",
}


def _blob(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in ("name", "title", "snippet", "url")
    )


def _name(row: dict[str, Any]) -> str:
    return str(row.get("name") or row.get("title") or "").split("—")[0].split("|")[0].strip()


def classify_orgs(hits: list[dict[str, Any]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rivals: list[dict[str, str]] = []
    writers: list[dict[str, str]] = []
    seen_r: set[str] = set()
    seen_w: set[str] = set()
    for raw in hits:
        if not isinstance(raw, dict):
            continue
        name = _name(raw)
        if not name or name.lower() in {"none", "unknown"}:
            continue
        url = str(raw.get("url") or "")
        blob = _blob(raw)
        row = {"name": name, "url": url}
        writer = bool(WRITER_MARKERS.search(blob)) and not (
            VENDOR_MARKERS.search(blob) and "law" not in blob.lower()
        )
        if writer or (WRITER_MARKERS.search(blob) and not VENDOR_MARKERS.search(blob)):
            key = name.lower()
            if key not in seen_w:
                writers.append(row)
                seen_w.add(key)
            continue
        key = name.lower()
        if key not in seen_r:
            rivals.append(row)
            seen_r.add(key)
    return rivals, writers


def none_found(n_searches: int, *, kind: str = "rivals") -> str | None:
    """Absence is a search count, and only after at least three searches."""
    if n_searches < 3:
        return None
    return f"none found in {n_searches} searches"


def prospects_with_links(
    rows: list[dict[str, Any]],
    evidence: str,
    *,
    sells_to_giants: bool = False,
) -> list[dict[str, Any]]:
    blob = evidence or ""
    kept: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not name or not url:
            continue
        if not re.search(re.escape(name), blob, re.I) and url not in blob:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        giant = key in GIANTS or bool(raw.get("giant"))
        if giant and not sells_to_giants:
            continue
        item = {"name": name, "url": url}
        if giant:
            item["giant"] = True
        kept.append(item)
        if len(kept) >= 10:
            break
    return kept


def rival_queries(problem: str, buyer: str, shape: str) -> list[str]:
    problem = " ".join((problem or "this problem").split())[:80]
    buyer = " ".join((buyer or "buyer").split())[:60]
    shape = " ".join((shape or "software").split())[:40]
    return [
        f"{problem} software",
        f"{problem} platform OR service",
        f"{buyer} vendor",
        f"{problem} {shape}",
    ]


def prospect_queries(buyer: str, place: str = "") -> list[str]:
    buyer = " ".join((buyer or "organization").split())[:60]
    place = " ".join((place or "").split())[:40]
    queries = [
        f"{buyer} association",
        f"{buyer} network",
        f"list of {buyer}",
    ]
    if place:
        queries[0] = f"{buyer} {place}"
        queries.append(f"{place} {buyer} association")
    return queries[:4]


def format_rivals(rows: list[dict[str, str]], n_searches: int) -> str:
    if rows:
        bits = []
        for row in rows[:8]:
            name = row.get("name") or ""
            url = row.get("url") or ""
            bits.append(f"{name} ({url})" if url else name)
        return "; ".join(bits)
    return none_found(n_searches, kind="rivals") or "not enough searches"


def format_writers(rows: list[dict[str, str]]) -> str:
    if not rows:
        return ""
    bits = []
    for row in rows[:8]:
        name = row.get("name") or ""
        url = row.get("url") or ""
        bits.append(f"{name} ({url})" if url else name)
    return "; ".join(bits)
