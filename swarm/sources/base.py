from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod

from swarm.models import Signal, SourceHealth
from swarm.settings import get_settings


class SourceAdapter(ABC):
    name: str

    @abstractmethod
    async def fetch(self) -> list[Signal]:
        """Return today's signals. Raise on hard failure; orchestrator records it."""

    timeout_s: float | None = None
    freshness_days: int = 1

    def enabled(self) -> bool:
        return True

    def availability(self) -> str:
        """ok, off, or needs key. off and needs key are not fetches and not dead."""
        if getattr(self, "_config_enabled", True) is False:
            return "off"
        key_attr = str(getattr(self, "_key_attr", "") or "")
        if key_attr and not str(getattr(get_settings(), key_attr, "") or "").strip():
            return "needs key"
        if not self.enabled():
            return "needs key" if key_attr else "off"
        return "ok"


async def collect_signals(sources: list[SourceAdapter]) -> tuple[list[Signal], list[SourceHealth]]:
    settings = get_settings()

    async def _one(src: SourceAdapter) -> tuple[list[Signal], SourceHealth]:
        state = src.availability()
        if state == "off":
            return [], SourceHealth(source=src.name, ok=True, count=0, error="off")
        if state == "needs key":
            return [], SourceHealth(source=src.name, ok=True, count=0, error="needs key")
        timeout = src.timeout_s or settings.source_timeout_s
        started = time.perf_counter()
        try:
            items = await asyncio.wait_for(src.fetch(), timeout=timeout)
            elapsed = int((time.perf_counter() - started) * 1000)
            limited = list(getattr(src, "rate_limited_queries", []) or [])
            error = None
            ok = True
            if limited:
                named = "; ".join(limited)
                error = f"429 on query: {named}"
                if not items:
                    ok = False
            return items, SourceHealth(
                source=src.name,
                ok=ok,
                count=len(items),
                error=error,
                elapsed_ms=elapsed,
                rate_limited=limited,
            )
        except Exception as exc:  # noqa: BLE001 — degraded-run tolerance
            elapsed = int((time.perf_counter() - started) * 1000)
            return [], SourceHealth(
                source=src.name,
                ok=False,
                count=0,
                error=f"{type(exc).__name__}: {exc}",
                elapsed_ms=elapsed,
            )

    results = await asyncio.gather(*[_one(s) for s in sources])
    signals: list[Signal] = []
    health: list[SourceHealth] = []
    for items, status in results:
        signals.extend(items)
        health.append(status)
    return signals, health
