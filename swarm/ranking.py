"""Within-source rank, then round-robin. Scores are not comparable across sources."""

from __future__ import annotations

from swarm.models import Signal


def select_round_robin(signals: list[Signal], limit: int) -> list[tuple[Signal, int]]:
    """Fill `limit` slots one-from-each-source, repeating until full.

    Within a source, rank 1 is the highest score. Source order is first-seen
    order so a run is stable. This does not touch dedup.
    """
    if limit <= 0 or not signals:
        return []
    order: list[str] = []
    buckets: dict[str, list[Signal]] = {}
    for signal in signals:
        if signal.source not in buckets:
            order.append(signal.source)
            buckets[signal.source] = []
        buckets[signal.source].append(signal)
    ranked: dict[str, list[tuple[Signal, int]]] = {}
    for source, items in buckets.items():
        ordered = sorted(items, key=lambda s: s.score, reverse=True)
        ranked[source] = [(sig, i) for i, sig in enumerate(ordered, start=1)]
    cursors = {source: 0 for source in order}
    chosen: list[tuple[Signal, int]] = []
    while len(chosen) < limit:
        progressed = False
        for source in order:
            idx = cursors[source]
            bucket = ranked[source]
            if idx >= len(bucket):
                continue
            chosen.append(bucket[idx])
            cursors[source] = idx + 1
            progressed = True
            if len(chosen) >= limit:
                break
        if not progressed:
            break
    return chosen
