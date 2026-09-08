"""A source at zero for N consecutive runs is dead, not quiet. Clears on any hit."""

from __future__ import annotations

from swarm.models import SourceHealth
from swarm.settings import get_settings


def annotate_dead_sources(
    current: list[SourceHealth],
    prior: list[tuple[int, list[dict]]],
) -> list[SourceHealth]:
    """`prior` is newest-first (run_id, source_health dump). Recoverable."""
    n = max(1, get_settings().source_dead_after_runs)
    out: list[SourceHealth] = []
    for item in current:
        if item.error == "skipped":
            out.append(item)
            continue
        if item.count > 0:
            item.dead = False
            item.last_ok = "this run"
            out.append(item)
            continue
        zeros = 1
        last_ok: str | None = None
        for run_id, blob in prior:
            past = _find(blob, item.source)
            if past is None:
                continue
            if past.get("error") == "skipped":
                continue
            if int(past.get("count") or 0) > 0:
                last_ok = f"run {run_id}"
                break
            zeros += 1
        item.last_ok = last_ok
        item.dead = zeros >= n
        out.append(item)
    return out


def _find(blob: list[dict], source: str) -> dict | None:
    for row in blob or []:
        if isinstance(row, dict) and row.get("source") == source:
            return row
    return None
