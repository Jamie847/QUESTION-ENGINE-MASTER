"""Turn a numeric series into a primary signal. The model never invents the number."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from swarm.models import Signal

Z_THRESHOLD = 2.0
TRAIL = 14
CAP_PER_RUN = 6


def emit_movers(
    *,
    source: str,
    series_id: str,
    label: str,
    unit: str,
    values: list[float],
    dates: list[str],
    url: str,
    vertical: str,
    cap: int = CAP_PER_RUN,
) -> list[Signal]:
    """Emit at most one signal when the latest change is unusual."""
    move = describe_move(values, dates, label=label, unit=unit)
    if move is None:
        return []
    text, data_date, raw = move
    return [
        Signal(
            source=source,
            title=text,
            url=url,
            snippet=f"{text} ({data_date}, {series_id})",
            score=min(9.0, 4.0 + abs(float(raw["z"]))),
            vertical_hints=[vertical] if vertical else [],
            raw={
                "series_id": series_id,
                "label": label,
                "unit": unit,
                "primary": True,
                **raw,
            },
        )
    ][:cap]


def describe_move(
    values: list[float],
    dates: list[str],
    *,
    label: str,
    unit: str,
) -> tuple[str, str, dict[str, Any]] | None:
    if len(values) < 3 or len(values) != len(dates):
        return None
    latest = values[-1]
    prior = values[-2]
    change = latest - prior
    trail = values[-TRAIL:] if len(values) >= 3 else values
    deltas = [trail[i] - trail[i - 1] for i in range(1, len(trail))]
    if len(deltas) < 2:
        return None
    mean = sum(deltas) / len(deltas)
    var = sum((d - mean) ** 2 for d in deltas) / len(deltas)
    std = math.sqrt(var)
    if std == 0 or math.isnan(std):
        return None
    z = (change - mean) / std
    if abs(z) < Z_THRESHOLD:
        return None
    larger = 1
    for older in reversed(deltas[:-1]):
        if abs(older) >= abs(change) - 1e-12:
            break
        larger += 1
    signed = _format_change(change, unit)
    streak = f"largest {'draw' if change < 0 else 'rise'} in {larger} periods"
    text = f"{label} {signed}, {streak}"
    data_date = dates[-1]
    return (
        text,
        data_date,
        {
            "latest": latest,
            "prior": prior,
            "change": change,
            "z": z,
            "data_date": data_date,
            "periods": larger,
        },
    )


def _format_change(change: float, unit: str) -> str:
    abs_val = abs(change)
    if abs_val >= 10:
        shown = f"{change:+.1f}"
    elif abs_val >= 1:
        shown = f"{change:+.2f}"
    else:
        shown = f"{change:+.3f}"
    unit = (unit or "").strip()
    if unit:
        return f"{shown}{'' if unit.startswith('%') else ' '}{unit}"
    return shown


def iso_today() -> str:
    return date.today().isoformat()
