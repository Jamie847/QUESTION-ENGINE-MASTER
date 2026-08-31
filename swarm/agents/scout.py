from __future__ import annotations

from pathlib import Path

from swarm.config import verticals
from swarm.ids import slug
from swarm.llm import LLM
from swarm.models import Brief, Signal, Velocity

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
                    "source_urls": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "headline",
                    "what_is_happening",
                    "why_now",
                    "who_is_affected",
                    "velocity",
                    "source_urls",
                ],
            },
        }
    },
    "required": ["briefs"],
}


def run_scouts(signals: list[Signal], llm: LLM, *, run_id: int = 0) -> list[Brief]:
    briefs: list[Brief] = []
    for cfg in verticals():
        subset = [s for s in signals if cfg["id"] in (s.vertical_hints or [])]
        if not subset:
            # last resort: keyword-unassigned high-score items, lightly
            subset = [s for s in signals if not s.vertical_hints][:8]
        subset = sorted(subset, key=lambda s: s.score, reverse=True)[:18]
        produced = _llm_briefs(cfg, subset, llm, run_id) or _fallback_briefs(
            cfg, subset, run_id
        )
        briefs.extend(produced)
    return briefs


def _llm_briefs(
    cfg: dict, signals: list[Signal], llm: LLM, run_id: int
) -> list[Brief] | None:
    if not signals or not llm.available:
        return None
    lines = [f"- {s.title} ({s.source}, score={s.score:.1f}) {s.url}" for s in signals]
    user = "Candidate signals:\n" + "\n".join(lines)
    system = PROMPT.format(vertical_name=cfg["name"], vertical_id=cfg["id"])
    data = llm.complete_json(system=system, user=user, schema=BRIEF_SCHEMA)
    if not data:
        return None
    out: list[Brief] = []
    for raw in data.get("briefs") or []:
        try:
            headline = raw["headline"]
            out.append(
                Brief(
                    id=f"r{run_id}-{cfg['id']}-{slug(headline)}",
                    vertical=cfg["id"],
                    headline=headline,
                    what_is_happening=raw.get("what_is_happening", ""),
                    why_now=raw.get("why_now", ""),
                    who_is_affected=raw.get("who_is_affected", ""),
                    velocity=Velocity(raw.get("velocity") or "unknown"),
                    sources=raw.get("source_urls") or [s.url for s in signals[:3] if s.url],
                    raw_signals=[s.source for s in signals[:4]],
                    score=max((s.score for s in signals[:3]), default=1.0),
                )
            )
        except Exception:
            continue
    return out or None


def _fallback_briefs(cfg: dict, signals: list[Signal], run_id: int) -> list[Brief]:
    out: list[Brief] = []
    for sig in signals[:6]:
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
            )
        )
    return out


def _who(vertical: str) -> str:
    return {
        "ai": "builders, regulators, and the firms buying inference",
        "health": "patients, clinicians, and the payers sitting between them",
        "business": "operators, allocators, and the workers on the wrong side of the adjustment",
    }.get(vertical, "people inside the institutions this actually touches")
