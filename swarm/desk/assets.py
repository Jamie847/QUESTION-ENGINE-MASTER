"""Operator-written assets profile. The system never invents it."""

from __future__ import annotations

from datetime import datetime, timezone

from swarm.db import session_scope
from swarm.orm import OperatorAssetsRow

HEADINGS = (
    ("businesses", "Businesses I run, and what they sell"),
    ("reach", "Who I can reach, and how"),
    ("skills", "Skills and team"),
    ("capital_time", "Capital and time I can commit"),
    ("wont_do", "Things I won't do"),
)


def empty_profile() -> dict[str, str]:
    return {key: "" for key, _label in HEADINGS}


def load_assets() -> dict[str, str]:
    with session_scope() as session:
        row = session.get(OperatorAssetsRow, 1)
        if row is None:
            return empty_profile()
        return {
            "businesses": row.businesses or "",
            "reach": row.reach or "",
            "skills": row.skills or "",
            "capital_time": row.capital_time or "",
            "wont_do": row.wont_do or "",
        }


def save_assets(payload: dict[str, str]) -> dict[str, str]:
    """Store only keys the Operator can edit. No generated fill-in."""
    clean = empty_profile()
    for key in clean:
        clean[key] = str(payload.get(key) or "")[:4000]
    with session_scope() as session:
        row = session.get(OperatorAssetsRow, 1)
        if row is None:
            row = OperatorAssetsRow(id=1)
            session.add(row)
        row.businesses = clean["businesses"]
        row.reach = clean["reach"]
        row.skills = clean["skills"]
        row.capital_time = clean["capital_time"]
        row.wont_do = clean["wont_do"]
        row.updated_at = datetime.now(timezone.utc)
    return clean
