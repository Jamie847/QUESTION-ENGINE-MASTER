"""One-shot deploy backfill. A second call records skip and rewrites nothing."""

from __future__ import annotations

from datetime import datetime, timezone

from swarm.db import session_scope
from swarm.memory.store import embed_all_pending
from swarm.orm import DeployMarkerRow

MARKER = "wo014_memory_backfill"


def backfill_already_ran() -> bool:
    with session_scope() as session:
        return session.get(DeployMarkerRow, MARKER) is not None


def _record_ran(detail: dict[str, int]) -> None:
    with session_scope() as session:
        row = session.get(DeployMarkerRow, MARKER)
        if row is None:
            session.add(
                DeployMarkerRow(
                    name=MARKER,
                    detail=detail,
                    ran_at=datetime.now(timezone.utc),
                )
            )
        else:
            row.detail = detail
            row.ran_at = datetime.now(timezone.utc)


def backfill_memory() -> dict[str, int]:
    empty = {"embedded": 0, "skipped": 0, "ok": 0}
    if backfill_already_ran():
        return {**empty, "skipped": 1}
    result = embed_all_pending()
    embedded = int(result.get("embedded") or 0)
    ok = 1 if result.get("ok") else 0
    counts = {"embedded": embedded, "skipped": 0, "ok": ok}
    if not result.get("ok"):
        return counts
    _record_ran(counts)
    return counts
