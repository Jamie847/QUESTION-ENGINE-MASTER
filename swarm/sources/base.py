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

    def enabled(self) -> bool:
        return True


async def collect_signals(sources: list[SourceAdapter]) -> tuple[list[Signal], list[SourceHealth]]:
    settings = get_settings()
    timeout = settings.source_timeout_s

    async def _one(src: SourceAdapter) -> tuple[list[Signal], SourceHealth]:
        if not src.enabled():
            return [], SourceHealth(source=src.name, ok=True, count=0, error="skipped")
        started = time.perf_counter()
        try:
            items = await asyncio.wait_for(src.fetch(), timeout=timeout)
            elapsed = int((time.perf_counter() - started) * 1000)
            return items, SourceHealth(
                source=src.name, ok=True, count=len(items), elapsed_ms=elapsed
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
