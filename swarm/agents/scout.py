from __future__ import annotations

from pathlib import Path

from swarm.config import verticals
from swarm.ids import slug
from swarm.llm import LLM
from swarm.models import Brief, Signal, Velocity
from swarm.primary import prefer_primary_urls
from swarm.ranking import select_round_robin
from swarm.settings import get_settings

SCOUT_SLOTS = 18


def take_round_robin(
    signals: list[Signal], slots: int = SCOUT_SLOTS
) -> list[tuple[Signal, int]]:
    """Honesty helpers and tests call this name. Ranking is within-source then round-robin."""
    return select_round_robin(signals, slots)

PROMPT = (Path(__file__).resolve().parent.parent / "prompts" / "scout.md").read_text(
    encoding="utf-8"
)

BRIEF_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "briefs": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "headline": {"type": "string"},
                    "what_is_happening": {"type": "string"},
                    "why_now": {"type": "string"},
                    "who_is_affected": {"type": "string"},
                    "velocity": {
                        "type": "string",
                        "enum": ["accelerating", "steady", "peaked", "unknown"],
                    },
                    "signal_refs": {"type": "array", "items": {"type": "string"}},
                    "source_urls": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "headline",
                    "what_is_happening",
                    "why_now",
                    "who_is_affected",
                    "velocity",
                    "signal_refs",
                    "source_urls",
                ],
            },
        }
    },
    "required": ["briefs"],
}


def signals_for_vertical(
    vertical_id: str, signals: list[Signal], *, limit: int | None = None
) -> list[tuple[Signal, int]]:
    subset = [s for s in signals if vertical_id in (s.vertical_hints or [])]
    if not subset:
        subset = [s for s in signals if not s.vertical_hints][:8]
    cap = get_settings().scout_signals_per_vertical if limit is None else limit
    return select_round_robin(subset, cap)


def format_signal_block(pairs: list[tuple[Signal, int]], *, snippet_chars: int | None = None) -> str:
    """Labels S1… are what the model cites. The snippet is the text it can quote."""
    limit = get_settings().snippet_chars if snippet_chars is None else snippet_chars
    lines: list[str] = []
    for n, (sig, rank) in enumerate(pairs, start=1):
        snippet = (sig.snippet or "").strip()[:limit]
        lines.append(
            f"- S{n} ({sig.source}, rank {rank}) {sig.title}\n"
            f"  {snippet}\n"
            f"  {sig.url}"
        )
    return "\n".join(lines)


def urls_from_model(
    raw: dict, labels: dict[str, Signal]
) -> list[str]:
    """Keep only URLs that belong to signals this scout was given."""
    allowed = {sig.url: sig.url for sig in labels.values() if sig.url}
    chosen: list[str] = []
    for ref in raw.get("signal_refs") or []:
        sig = labels.get(str(ref).strip())
        if sig and sig.url and sig.url not in chosen:
            chosen.append(sig.url)
    for url in raw.get("source_urls") or []:
        if url in allowed and url not in chosen:
            chosen.append(url)
    return chosen


def run_scouts(signals: list[Signal], llm: LLM, *, run_id: int = 0) -> list[Brief]:
    briefs: list[Brief] = []
    seen: set[tuple[str, str]] = set()
    counts: dict[str, int] = {}
    for cfg in verticals():
        pairs = signals_for_vertical(cfg["id"], signals)
        for sig, _rank in pairs:
            key = (sig.source, sig.url or sig.title)
            if key in seen:
                continue
            seen.add(key)
            counts[sig.source] = counts.get(sig.source, 0) + 1
        produced = _llm_briefs(cfg, pairs, llm, run_id)
        if produced is None:
            if llm.available:
                produced = []
            else:
                produced = _fallback_briefs(cfg, pairs, run_id)
        briefs.extend(produced)
    run_scouts.seen_by_source = counts  # type: ignore[attr-defined]
    return briefs


def _llm_briefs(
    cfg: dict, pairs: list[tuple[Signal, int]], llm: LLM, run_id: int
) -> list[Brief] | None:
    if not pairs or not llm.available:
        return None
    labels = {f"S{n}": sig for n, (sig, _rank) in enumerate(pairs, start=1)}
    user = "Candidate signals:\n" + format_signal_block(pairs)
    system = PROMPT.format(vertical_name=cfg["name"], vertical_id=cfg["id"])
    data = llm.complete_json(system=system, user=user, schema=BRIEF_SCHEMA)
    if not data:
        return None
    writer = llm.writer_name()
    out: list[Brief] = []
    for raw in data.get("briefs") or []:
        try:
            headline = raw["headline"]
            claimed = urls_from_model(raw, labels)
            urls = prefer_primary_urls(
                " ".join(
                    [
                        headline,
                        raw.get("what_is_happening", ""),
                        raw.get("why_now", ""),
                    ]
                ),
                claimed,
                [sig for sig, _rank in pairs],
            )
            out.append(
                Brief(
                    id=f"r{run_id}-{cfg['id']}-{slug(headline)}",
                    vertical=cfg["id"],
                    headline=headline,
                    what_is_happening=raw.get("what_is_happening", ""),
                    why_now=raw.get("why_now", ""),
                    who_is_affected=raw.get("who_is_affected", ""),
                    velocity=Velocity(raw.get("velocity") or "unknown"),
                    sources=urls,
                    raw_signals=[sig.source for sig, _rank in pairs[:4]],
                    score=max((sig.score for sig, _rank in pairs[:3]), default=1.0),
                    written_by=writer,
                )
            )
        except Exception:
            continue
    return out or None


def _fallback_briefs(
    cfg: dict, pairs: list[tuple[Signal, int]], run_id: int
) -> list[Brief]:
    out: list[Brief] = []
    for sig, _rank in pairs[:6]:
        velocity = Velocity.accelerating if sig.score >= 8 else Velocity.steady
        out.append(
            Brief(
                id=f"r{run_id}-{cfg['id']}-{slug(sig.title)}",
                vertical=cfg["id"],
                headline=sig.title,
                what_is_happening=sig.snippet or sig.title,
                why_now=f"Attention on {sig.source} is elevated (score {sig.score:.0f}).",
                who_is_affected=_who(cfg["id"]),
                velocity=velocity,
                sources=[sig.url] if sig.url else [],
                raw_signals=[sig.source],
                score=sig.score,
                written_by="template",
            )
        )
    return out


def _who(vertical: str) -> str:
    return {
        "ai": "builders, regulators, and the firms buying inference",
        "health": "patients, clinicians, and the payers sitting between them",
        "business": "operators, allocators, and the workers on the wrong side of the adjustment",
        "science": "labs, funders, and the fields waiting on the result",
        "education": "students, teachers, and the institutions that credential them",
        "geopolitics": "governments, firms in the blast radius, and the people crossing the border",
        "commodities": "producers, traders, and the operators who price the physical",
    }.get(vertical, "people inside the institutions this actually touches")
