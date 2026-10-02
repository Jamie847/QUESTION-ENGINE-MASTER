"""Pursue / Park / Kill. History is kept."""

from __future__ import annotations

from datetime import datetime, timezone

from swarm.db import session_scope
from swarm.orm import OpportunityRow, OpportunityVerdictRow

ALLOWED = {"pursue", "park", "kill"}


def apply_verdict(opportunity_id: str, verdict: str, why: str) -> dict:
    label = (verdict or "").strip().lower()
    if label not in ALLOWED:
        raise ValueError(f"unknown verdict: {verdict}")
    note = (why or "").strip()
    if label in {"pursue", "kill"} and not note:
        raise ValueError(f"{label} requires a one-line why")
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        row = session.get(OpportunityRow, opportunity_id)
        if row is None:
            raise ValueError("unknown opportunity")
        session.add(
            OpportunityVerdictRow(
                opportunity_id=opportunity_id,
                verdict=label,
                why=note,
                decided_at=now,
            )
        )
        row.latest_verdict = label
        row.latest_verdict_why = note
        row.latest_verdict_at = now
    return {"ok": True, "verdict": label, "why": note, "at": now.isoformat()}


def verdict_history(opportunity_id: str) -> list[dict]:
    with session_scope() as session:
        rows = (
            session.query(OpportunityVerdictRow)
            .filter(OpportunityVerdictRow.opportunity_id == opportunity_id)
            .order_by(OpportunityVerdictRow.id)
            .all()
        )
        return [
            {
                "verdict": r.verdict,
                "why": r.why,
                "at": r.decided_at.isoformat() if r.decided_at else None,
            }
            for r in rows
        ]
