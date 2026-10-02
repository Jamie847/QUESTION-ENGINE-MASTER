"""FRED series. Free key. The adapter writes the number."""

from __future__ import annotations

from typing import Any

import httpx

from swarm.config import verticals
from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.movers import emit_movers

API = "https://api.stlouisfed.org/fred/series/observations"


def extract_points(payload: dict[str, Any]) -> tuple[list[float], list[str]]:
    rows = payload.get("observations") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return [], []
    values: list[float] = []
    dates: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("value")
        if raw in {None, ".", ""}:
            continue
        try:
            number = float(raw)
        except (TypeError, ValueError):
            continue
        dates.append(str(row.get("date") or ""))
        values.append(number)
    return values, dates


class FredSource(SourceAdapter):
    name = "fred"
    _key_attr = "fred_api_key"

    def enabled(self) -> bool:
        return bool(get_settings().fred_api_key)

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        key = settings.fred_api_key
        if not key:
            return []
        headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
        signals: list[Signal] = []
        async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
            for row in _series_for("fred"):
                resp = await client.get(
                    API,
                    params={
                        "series_id": row["id"],
                        "api_key": key,
                        "file_type": "json",
                        "sort_order": "asc",
                        "limit": 24,
                    },
                )
                resp.raise_for_status()
                values, dates = extract_points(resp.json())
                signals.extend(
                    emit_movers(
                        source=self.name,
                        series_id=row["id"],
                        label=row["label"],
                        unit=row.get("unit") or "",
                        values=values,
                        dates=dates,
                        url=f"https://fred.stlouisfed.org/series/{row['id']}",
                        vertical=row.get("vertical") or "commodities",
                    )
                )
        return signals


def _series_for(provider: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for vertical in verticals():
        for item in vertical.get("series") or []:
            if str(item.get("provider") or "") != provider:
                continue
            rows.append({**item, "vertical": vertical["id"]})
    return rows
