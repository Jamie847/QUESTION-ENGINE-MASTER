"""Which questions reach the desk."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from swarm.settings import get_settings

HIDDEN = {"unlinked", "unverified", "pre-wo006"}


@dataclass
class DeskSkip:
    id: str
    skip_reason: str


def _status(row: Any) -> str:
    value = getattr(row, "status", "")
    return value.value if hasattr(value, "value") else str(value or "")


def _is_model_written(row: Any) -> bool:
    return str(getattr(row, "written_by", "") or "").startswith("model:")


def _is_saved_since(row: Any, previous_started: datetime | None) -> bool:
    if not getattr(row, "promoted", False):
        return False
    when = getattr(row, "promoted_at", None)
    if when is None:
        return False
    if previous_started is None:
        return True
    if when.tzinfo is None and previous_started.tzinfo is not None:
        when = when.replace(tzinfo=previous_started.tzinfo)
    return when >= previous_started


def select_for_desk(
    questions: list[Any],
    *,
    previous_started: datetime | None,
    max_n: int | None = None,
) -> tuple[list[Any], list[DeskSkip]]:
    cap = max_n if max_n is not None else get_settings().opportunity_max
    skipped: list[DeskSkip] = []
    saved: list[Any] = []
    ranked: list[Any] = []
    seen: set[str] = set()

    for row in questions:
        qid = str(getattr(row, "id", "") or "")
        prov = (getattr(row, "provenance", "") or "").strip()
        if prov in HIDDEN:
            skipped.append(DeskSkip(id=qid, skip_reason=prov))
            continue
        if not _is_model_written(row):
            skipped.append(DeskSkip(id=qid, skip_reason="not model-written"))
            continue
        if _is_saved_since(row, previous_started) and qid not in seen:
            saved.append(row)
            seen.add(qid)
            continue
        if _status(row) == "curated" and qid not in seen:
            ranked.append(row)

    ranked.sort(key=lambda r: (getattr(r, "rank", None) is None, getattr(r, "rank", 999)))
    top = [row for row in ranked if getattr(row, "rank", None) is not None][:3]
    picks: list[Any] = []
    for row in saved + top:
        qid = str(row.id)
        if qid in {p.id for p in picks}:
            continue
        picks.append(row)
        if len(picks) >= cap:
            break
    return picks, skipped
