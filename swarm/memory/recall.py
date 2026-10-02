"""Desk recall: dated past cards and verdicts, never current fact."""

from __future__ import annotations

from typing import Any

from swarm.memory.store import search_memory

RECALL_KINDS = ("opportunity", "verdict")

PROMPT_RULES = (
    "Past items from memory (dated — not current fact). Re-check any claim they make. "
    "If a similar idea was Killed, say what is different now, or say that nothing is. "
    "If a similar idea was Parked, say whether today's evidence changes that."
)


def recall_for_desk(text: str, *, run_id: int, limit: int = 3) -> list[dict[str, Any]]:
    hits = search_memory(
        text,
        kinds=list(RECALL_KINDS),
        exclude_run=run_id,
        limit=limit,
    )["results"]
    return hits[:limit]


def format_for_prompt(related: list[dict[str, Any]]) -> str:
    lines = [PROMPT_RULES, ""]
    if not related:
        lines.append("nothing related yet")
        return "\n".join(lines)
    for item in related:
        bits = [
            item.get("item_date") or "undated",
            item.get("kind") or "",
            item.get("title") or "",
        ]
        if item.get("verdict"):
            bits.append(str(item["verdict"]))
        head = " · ".join(b for b in bits if b)
        why = item.get("verdict_why") or ""
        lines.append(f"- {head}" + (f" — {why}" if why else ""))
        body = (item.get("text") or "").strip()
        if body:
            lines.append(f"  {body[:400]}")
    return "\n".join(lines)
