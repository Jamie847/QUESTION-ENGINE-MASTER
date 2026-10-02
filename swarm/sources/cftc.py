"""CFTC Commitments of Traders. No key. Speculator positioning."""

from __future__ import annotations

from typing import Any

import httpx

from swarm.config import verticals
from swarm.models import Signal
from swarm.settings import get_settings
from swarm.sources.base import SourceAdapter
from swarm.sources.movers import emit_movers

API = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"


def cftc_params(market: str, *, limit: int = 80) -> dict[str, str]:
    needle = (market or "").replace("'", "''").strip().upper()
    where = (
        f"upper(market_and_exchange_names) like '%{needle}%'"
        if needle
        else "report_date_as_yyyy_mm_dd IS NOT NULL"
    )
    return {
        "$limit": str(limit),
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$where": where,
    }


def extract_points(rows: list[dict[str, Any]], market: str) -> tuple[list[float], list[str]]:
    values: list[float] = []
    dates: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("market_and_exchange_names") or row.get("contract_market_name") or "")
        if market and market.lower() not in name.lower():
            continue
        raw = row.get("noncomm_positions_long_all") or row.get("noncomm_positions")
        try:
            number = float(str(raw).replace(",", ""))
        except (TypeError, ValueError):
            continue
        report = str(row.get("report_date_as_yyyy_mm_dd") or row.get("yyyy_report_date_wk_start") or "")
        if not report:
            continue
        dates.append(report[:10])
        values.append(number)
    paired = sorted(zip(dates, values), key=lambda item: item[0])
    if not paired:
        return [], []
    out_dates, out_values = zip(*paired)
    return list(out_values), list(out_dates)


class CftcSource(SourceAdapter):
    name = "cftc"

    async def fetch(self) -> list[Signal]:
        settings = get_settings()
        headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
        markets = [
            item
            for vertical in verticals()
            for item in (vertical.get("series") or [])
            if str(item.get("provider") or "") == "cftc"
        ]
        if not markets:
            return []
        signals: list[Signal] = []
        async with httpx.AsyncClient(timeout=settings.source_timeout_s, headers=headers) as client:
            for item in markets:
                market = str(item.get("market") or item.get("id") or "")
                resp = await client.get(API, params=cftc_params(market))
                resp.raise_for_status()
                payload = resp.json()
                rows = payload if isinstance(payload, list) else []
                values, dates = extract_points(rows, market)
                movers = emit_movers(
                    source=self.name,
                    series_id=str(item.get("id") or item.get("market") or "cot"),
                    label=item.get("label") or "CFTC non-commercial longs",
                    unit=item.get("unit") or "contracts",
                    values=values,
                    dates=dates,
                    url="https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
                    vertical="commodities",
                )
                if movers:
                    signals.extend(movers)
                    continue
                if values and dates:
                    latest = values[-1]
                    label = item.get("label") or "CFTC non-commercial longs"
                    unit = item.get("unit") or "contracts"
                    text = f"{label} at {latest:,.0f} {unit} as of {dates[-1]}"
                    signals.append(
                        Signal(
                            source=self.name,
                            title=text,
                            url="https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
                            snippet=text,
                            score=3.4,
                            vertical_hints=["commodities"],
                            raw={
                                "series_id": str(item.get("id") or market or "cot"),
                                "label": label,
                                "unit": unit,
                                "latest": latest,
                                "data_date": dates[-1],
                                "primary": True,
                                "mover": False,
                            },
                        )
                    )
        return signals
