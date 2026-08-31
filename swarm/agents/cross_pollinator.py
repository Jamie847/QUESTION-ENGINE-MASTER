from __future__ import annotations

from itertools import combinations
from pathlib import Path

from swarm.ids import slug
from swarm.llm import LLM
from swarm.models import Brief, Coverage, Intersection

PROMPT = (
    Path(__file__).resolve().parent.parent / "prompts" / "cross_pollinator.md"
).read_text(encoding="utf-8")

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "intersections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "verticals": {"type": "array", "items": {"type": "string"}},
                    "thesis": {"type": "string"},
                    "surprise": {"type": "number"},
                    "plausibility": {"type": "number"},
                    "coverage": {
                        "type": "string",
                        "enum": ["none", "thin", "crowded", "unknown"],
                    },
                    "coverage_notes": {"type": "string"},
                    "accepted": {"type": "boolean"},
                    "reject_reason": {"type": "string"},
                    "brief_headlines": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "verticals",
                    "thesis",
                    "surprise",
                    "plausibility",
                    "coverage",
                    "accepted",
                    "reject_reason",
                ],
            },
        }
    },
    "required": ["intersections"],
}


def run_cross_pollinator(briefs: list[Brief], llm: LLM) -> list[Intersection]:
    produced = _llm(briefs, llm) or _fallback(briefs)
    # Always persist rejects. If the model forgot, synthesize a few.
    if not any(not i.accepted for i in produced):
        produced.extend(_obvious_rejects(briefs))
    return produced


def _llm(briefs: list[Brief], llm: LLM) -> list[Intersection] | None:
    if not briefs or not llm.available:
        return None
    lines = [
        f"- [{b.vertical}] {b.headline} — {b.what_is_happening} (who: {b.who_is_affected})"
        for b in briefs
    ]
    data = llm.complete_json(
        system=PROMPT,
        user="Today's briefs:\n" + "\n".join(lines),
        schema=SCHEMA,
        reserve=True,
        max_tokens=5000,
    )
    if not data:
        return None
    by_headline = {b.headline: b for b in briefs}
    out: list[Intersection] = []
    for raw in data.get("intersections") or []:
        try:
            thesis = raw["thesis"]
            heads = raw.get("brief_headlines") or []
            brief_ids = [by_headline[h].id for h in heads if h in by_headline]
            out.append(
                Intersection(
                    id=slug(thesis),
                    verticals=raw.get("verticals") or [],
                    thesis=thesis,
                    surprise=float(raw.get("surprise") or 0),
                    plausibility=float(raw.get("plausibility") or 0),
                    coverage=Coverage(raw.get("coverage") or "unknown"),
                    coverage_notes=raw.get("coverage_notes") or "",
                    accepted=bool(raw.get("accepted")),
                    reject_reason=raw.get("reject_reason") or "",
                    brief_ids=brief_ids,
                )
            )
        except Exception:
            continue
    return out or None


def _fallback(briefs: list[Brief]) -> list[Intersection]:
    by_v: dict[str, list[Brief]] = {}
    for b in briefs:
        by_v.setdefault(b.vertical, []).append(b)
    ids = list(by_v.keys())
    accepted: list[Intersection] = []
    rejected: list[Intersection] = []
    for a, b in combinations(ids, 2):
        left = by_v[a][:3]
        right = by_v[b][:3]
        for i, (x, y) in enumerate(zip(left, right)):
            overlap = _token_overlap(x.headline, y.headline)
            surprise = max(0.2, min(0.95, 1.0 - overlap))
            thesis = (
                f"{x.headline.rstrip('.')} is colliding with {y.headline.rstrip('.')} "
                f"— the people who have to live in both rooms are not the ones writing the commentary."
            )
            item = Intersection(
                id=slug(thesis),
                verticals=[a, b],
                thesis=thesis,
                surprise=round(surprise, 2),
                plausibility=round(0.55 + (x.score + y.score) / 200.0, 2),
                coverage=_coverage_from_overlap(overlap),
                coverage_notes="Heuristic coverage from headline overlap (no search key).",
                accepted=surprise >= 0.45 and i < 2,
                reject_reason="" if surprise >= 0.45 and i < 2 else "pairing is too on-the-nose or a restatement of one brief",
                brief_ids=[x.id, y.id],
            )
            (accepted if item.accepted else rejected).append(item)
    return accepted[:8] + rejected[:6]


def _obvious_rejects(briefs: list[Brief]) -> list[Intersection]:
    if len(briefs) < 2:
        return []
    a, b = briefs[0], briefs[1]
    thesis = f"{a.vertical} × {b.vertical}: generic pairing of today's top headlines"
    return [
        Intersection(
            id=slug(thesis + "-reject"),
            verticals=[a.vertical, b.vertical],
            thesis=thesis,
            surprise=0.15,
            plausibility=0.8,
            coverage=Coverage.crowded,
            accepted=False,
            reject_reason="headline-level pairing with no mechanism",
            brief_ids=[a.id, b.id],
        )
    ]


def _token_overlap(a: str, b: str) -> float:
    sa, sb = set(a.lower().split()), set(b.lower().split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _coverage_from_overlap(overlap: float) -> Coverage:
    if overlap > 0.35:
        return Coverage.crowded
    if overlap > 0.12:
        return Coverage.thin
    return Coverage.unknown
