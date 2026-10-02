"""EIA series. Free key. Numbers come from the series, never the model."""

from __future__ import annotations

from typing import Any

import httpx

from swarm.config import verticals
from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.movers import emit_movers

API = "https://api.eia.gov/v2/seriesid/{series_id}"


def extract_points(payload: dict[str, Any]) -> tuple[list[float], list[str]]:
    response = payload.get("response") if isinstance(payload, dict) else None
    rows = (response or {}).get("data") if isinstance(response, dict) else None
    if not isinstance(rows, list):
        return [], []
    values: list[float] = []
    dates: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        period = str(row.get("period") or "")
        raw = row.get("value")
        try:
            number = float(raw)
        except (TypeError, ValueError):
            continue
        if period:
            dates.append(period)
            values.append(number)
    paired = sorted(zip(dates, values), key=lambda item: item[0])
    if not paired:
        return [], []
    out_dates, out_values = zip(*paired)
    return list(out_values), list(out_dates)


class EiaSource(SourceAdapter):
    name = "eia"
    _key_attr = "eia_api_key"

    def enabled(self) -> bool:
        return bool(get_settings().eia_api_key)

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        key = settings.eia_api_key
        if not key:
            return []
        headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
        series_rows = _series_for("eia")
        signals: list[Signal] = []
        async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
            for row in series_rows:
                resp = await client.get(
                    API.format(series_id=row["id"]),
                    params={"api_key": key, "length": 24},
                )
                resp.raise_for_status()
                values, dates = extract_points(resp.json())
                scale = float(row.get("scale") or 1)
                values = [v * scale for v in values]
                signals.extend(
                    emit_movers(
                        source=self.name,
                        series_id=row["id"],
                        label=row["label"],
                        unit=row.get("unit") or "",
                        values=values,
                        dates=dates,
                        url=row.get("url") or f"https://www.eia.gov/opendata/browser/seds?sourcekey={row['id']}",
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
