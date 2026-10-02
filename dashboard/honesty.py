"""What the Operator can see about sources. Never invent a link."""

from __future__ import annotations

from collections import Counter
from typing import Any

from swarm.agents.scout import SCOUT_SLOTS, take_round_robin
from swarm.config import lenses, verticals
from swarm.models import Signal
from swarm.primary import (
    domain_of,
    is_primary,
)

UNRECORDED = "sources not recorded"
_HIDDEN = {"unlinked", "pre-wo006", "unverified"}
_BANNED = ("quietly", "silently")


def from_cites(
    question: Any,
    briefs_by_id: dict[str, Any],
    signals_by_url: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Labels come from the signal behind each URL. Headline is the summary."""
    empty = {"summary": "", "cites": [], "unrecorded": True}
    prov = (getattr(question, "provenance", "") or "").strip()
    if prov in _HIDDEN:
        return empty
    related = [
        briefs_by_id[bid]
        for bid in (getattr(question, "brief_ids", None) or [])
        if bid in briefs_by_id
    ]
    if not related:
        return empty
    signals_by_url = signals_by_url or {}
    claimed: list[str] = []
    for brief in related:
        claimed.extend(u for u in (getattr(brief, "sources", None) or []) if u)
    urls = claimed
    if not urls:
        return empty
    cites: list[dict[str, Any]] = []
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        sig = signals_by_url.get(url)
        host = domain_of(url)
        source = getattr(sig, "source", "") if sig is not None else ""
        title = (getattr(sig, "title", "") if sig is not None else "") or host
        cites.append(
            {
                "title": title,
                "domain": host,
                "url": url,
                "source": source,
                "primary": is_primary(source=source, url=url),
            }
        )
    summary = next((b.headline for b in related if getattr(b, "headline", "")), "")
    return {"summary": summary, "cites": cites[:5], "unrecorded": False}


def from_line(
    question: Any,
    briefs_by_id: dict[str, Any],
    signals_by_url: dict[str, Any] | None = None,
) -> str:
    cites = from_cites(question, briefs_by_id, signals_by_url)
    if cites["unrecorded"]:
        return UNRECORDED
    bits: list[str] = []
    if cites["summary"]:
        bits.append(cites["summary"])
    labels = [f"{c['title']} ({c['domain']})" for c in cites["cites"] if c.get("domain")]
    if labels:
        bits.append(" · ".join(labels))
    return " — ".join(bits) if bits else UNRECORDED


def fetch_counts(signals: list[Any]) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for sig in signals:
        counts[sig.source] += 1
    return counts.most_common()


def scout_seen(signals: list[Any]) -> list[dict[str, Any]]:
    modeled = [
        sig
        if isinstance(sig, Signal)
        else Signal(
            source=sig.source,
            title=sig.title or "untitled",
            url=sig.url or "",
            score=sig.score or 0.0,
            vertical_hints=list(sig.vertical_hints or []),
        )
        for sig in signals
    ]
    out: list[dict[str, Any]] = []
    for cfg in verticals():
        subset = [s for s in modeled if cfg["id"] in (s.vertical_hints or [])]
        taken = take_round_robin(subset, SCOUT_SLOTS)
        counts: Counter[str] = Counter(sig.source for sig, _rank in taken)
        out.append(
            {
                "id": cfg["id"],
                "name": cfg["name"],
                "n": len(taken),
                "counts": counts.most_common(),
            }
        )
    return out


def bank_groups(bank: list[Any]) -> list[tuple[str, str, list[Any]]]:
    """A two-vertical question is filed under each of its tags.

    The All view uses the bank list as-is (once). These groups are the
    vertical filter only.
    """
    names = {v["id"]: v["name"] for v in verticals()}
    grouped: dict[str, list[Any]] = {}
    for q in bank:
        verts = list(getattr(q, "verticals", None) or [])
        if not verts:
            grouped.setdefault("uncategorized", []).append(q)
            continue
        for key in verts:
            grouped.setdefault(key, []).append(q)
    order = [v["id"] for v in verticals()] + ["uncategorized"]
    result = []
    for key in order:
        if key in grouped:
            result.append((key, names.get(key, key), grouped[key]))
    for key, qs in grouped.items():
        if key not in order:
            result.append((key, names.get(key, key), qs))
    return result


def _is_debug_warning(text: str) -> bool:
    low = text.lower()
    return (
        text.startswith("writer_ok_calls=")
        or text.startswith("writer used")
        or text.startswith("Anthropic:")
        or "anthropic_api_key" in low
        or "volume=" in low
        or "judgment=" in low
    )


def split_warnings(warnings: list[Any] | None) -> tuple[list[str], list[str]]:
    page: list[str] = []
    debug: list[str] = []
    for raw in warnings or []:
        text = str(raw)
        if _is_debug_warning(text):
            debug.append(text)
        else:
            page.append(text)
    return page, debug


def model_written_line(questions: list[Any]) -> str:
    names = {ln["id"]: ln["name"] for ln in lenses()}
    counts: Counter[str] = Counter()
    for q in questions:
        if str(getattr(q, "written_by", "") or "").startswith("model:"):
            counts[getattr(q, "lens", "") or "unknown"] += 1
    total = sum(counts.values())
    parts = [f"{names.get(ln['id'], ln['id'])} {counts.get(ln['id'], 0)}" for ln in lenses()]
    return f"{total} model-written · " + " · ".join(parts)


def sources_read_line(counts: list[tuple[str, int]]) -> str:
    if not counts:
        return "Read: nothing stored"
    return "Read: " + " · ".join(f"{src} {n}" for src, n in counts)


def pairing_reason(warnings: list[Any] | None) -> str:
    for raw in warnings or []:
        text = str(raw)
        if "topic pairing" in text.lower() or text.startswith("No topic pairings"):
            return text
    return "No topic pairings this run."


def failure_lines_from_warnings(warnings: list[Any] | None) -> list[str]:
    """Stage / model / category lines. No provider bodies (WO-005, WO-010 R4)."""
    from dashboard.public_text import public_warning

    out: list[str] = []
    for raw in warnings or []:
        text = str(raw)
        low = text.lower()
        keep = (
            text.startswith(
                ("Scouting:", "Topic pairing:", "Writing questions:", "Judging:")
            )
            or text.startswith("No topic pairings")
            or "refused by" in low
            or "recovered on" in low
            or " timeout on " in f" {low}"
            or "rate limit on" in low
            or "provider error on" in low
        )
        if not keep:
            continue
        shown = public_warning(text)
        if shown and shown not in out:
            out.append(shown)
    return out


def checked_urls(question: Any, briefs_by_id: dict[str, Any] | None) -> list[str]:
    """URLs that survived the scout-input check and still sit on the brief."""
    if not briefs_by_id:
        return []
    out: list[str] = []
    for bid in getattr(question, "brief_ids", None) or []:
        brief = briefs_by_id.get(bid)
        if brief is None:
            continue
        for url in getattr(brief, "sources", None) or []:
            if url and url not in out:
                out.append(url)
    return out


def question_is_linked(question: Any, briefs_by_id: dict[str, Any] | None) -> bool:
    prov = (getattr(question, "provenance", "") or "").strip()
    if prov in _HIDDEN:
        return False
    return bool(checked_urls(question, briefs_by_id))


def sources_linked_line(
    questions: list[Any], briefs_by_id: dict[str, Any] | None = None
) -> tuple[str, str]:
    rows = list(questions)
    total = len(rows)
    if briefs_by_id is None:
        linked = sum(
            1
            for q in rows
            if (getattr(q, "provenance", "") or "").strip() == "linked"
        )
    else:
        linked = sum(1 for q in rows if question_is_linked(q, briefs_by_id))
    line = f"Sources linked: {linked} of {total}"
    warn = ""
    if total and (linked / total) < 0.8:
        warn = f"Sources linked below 80% ({linked} of {total})."
    return line, warn


def banned_words_line(questions: list[Any], intersections: list[Any] | None = None) -> str:
    hits = 0
    for q in questions:
        blob = " ".join(
            [
                str(getattr(q, "text", "") or ""),
                str(getattr(q, "title", "") or ""),
                str(getattr(q, "context", "") or ""),
            ]
        ).lower()
        hits += sum(blob.count(word) for word in _BANNED)
    for item in intersections or []:
        blob = str(getattr(item, "thesis", "") or "").lower()
        hits += sum(blob.count(word) for word in _BANNED)
    return f"Banned words: {hits}"
