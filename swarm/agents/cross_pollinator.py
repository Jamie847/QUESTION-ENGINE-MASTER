from __future__ import annotations

from itertools import combinations
from pathlib import Path

from swarm.ids import slug
from swarm.llm import LLM
from swarm.models import Brief, Coverage, Intersection
from swarm.sources.routing import topic

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


def run_cross_pollinator(
    briefs: list[Brief], llm: LLM, *, run_id: int = 0
) -> list[Intersection]:
    produced = _llm(briefs, llm, run_id)
    if produced is None:
        if llm.available:
            return []
        produced = _fallback(briefs, run_id)
    # Keyless only: if the model forgot rejects, synthesize a few.
    if not llm.available and not any(not i.accepted for i in produced):
        produced.extend(_obvious_rejects(briefs, run_id))
    return produced


def _llm(briefs: list[Brief], llm: LLM, run_id: int) -> list[Intersection] | None:
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
        judgment=True,
        max_tokens=5000,
        estimate_in=4000,
        estimate_out=2500,
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
                    id=f"r{run_id}-{slug(thesis)}",
                    verticals=raw.get("verticals") or [],
                    thesis=thesis,
                    surprise=float(raw.get("surprise") or 0),
                    plausibility=float(raw.get("plausibility") or 0),
                    coverage=Coverage(raw.get("coverage") or "unknown"),
                    coverage_notes=raw.get("coverage_notes") or "",
                    accepted=bool(raw.get("accepted")),
                    reject_reason=raw.get("reject_reason") or "",
                    brief_ids=brief_ids,
                    written_by=llm.writer_name(judgment=True),
                )
            )
        except Exception:
            continue
    return out or None


_STAKE_WORDS = {
    "care": (
        "hospital", "patient", "clinic", "nurse", "doctor", "medicaid",
        "medicare", "drug", "fda", "cancer", "longevity", "dementia",
        "fertility", "ivf", "trial",
    ),
    "labor": (
        "worker", "layoff", "remote", "staff", "job", "aide", "nurse",
        "hiring", "wage",
    ),
    "capital": (
        "bank", "fed", "ipo", "funding", "price", "pay", "budget",
        "enterprise", "tariff", "inflation",
    ),
    "compute": (
        "model", "gpu", "inference", "cloud", "agent", "llm", "claude",
        "openai", "chip",
    ),
}


def _stakes(text: str) -> set[str]:
    blob = text.lower()
    return {name for name, words in _STAKE_WORDS.items() if any(w in blob for w in words)}


def _fallback(briefs: list[Brief], run_id: int) -> list[Intersection]:
    by_v: dict[str, list[Brief]] = {}
    for b in briefs:
        by_v.setdefault(b.vertical, []).append(b)
    ids = list(by_v.keys())
    accepted: list[Intersection] = []
    rejected: list[Intersection] = []
    for a, b in combinations(ids, 2):
        candidates: list[tuple[float, Brief, Brief, set[str]]] = []
        for x in by_v[a][:5]:
            for y in by_v[b][:5]:
                shared = _stakes(x.headline) & _stakes(y.headline)
                overlap = _token_overlap(x.headline, y.headline)
                # Shared stake → plausible. No shared stake → interesting only if we reject it.
                score = (0.4 if shared else 0.1) + min(x.score, 8) / 40 + min(y.score, 8) / 40
                candidates.append((score, x, y, shared))
        candidates.sort(key=lambda t: t[0], reverse=True)
        for i, (score, x, y, shared) in enumerate(candidates[:4]):
            overlap = _token_overlap(x.headline, y.headline)
            surprise = max(0.25, min(0.9, 0.75 - overlap + (0.05 if not shared else 0.0)))
            left, right = topic(x.headline, words=8), topic(y.headline, words=8)
            if shared:
                thesis = (
                    f"{left} and {right} share a {next(iter(shared))} stake "
                    f"that neither vertical's commentary is naming."
                )
                accept = i < 2
                reason = "" if accept else "weaker pairing than the ones already kept"
            else:
                thesis = f"{left} × {right} — two headlines, no shared mechanism."
                accept = False
                reason = "no shared mechanism, just two headlines"
            item = Intersection(
                id=f"r{run_id}-{slug(thesis)}",
                verticals=[a, b],
                thesis=thesis,
                surprise=round(surprise, 2),
                plausibility=round(min(0.95, 0.35 + score), 2),
                coverage=_coverage_from_overlap(overlap),
                coverage_notes="Heuristic coverage from headline overlap (no search key).",
                accepted=accept,
                reject_reason=reason,
                brief_ids=[x.id, y.id],
                written_by="template",
            )
            (accepted if item.accepted else rejected).append(item)
    if not accepted and rejected:
        promoted, rejected = rejected[:2], rejected[2:]
        for item in promoted:
            item.accepted = True
            item.reject_reason = ""
            item.coverage_notes = (
                f"{item.coverage_notes} Speculative pairing (no shared stake)."
            ).strip()
        accepted = promoted
    return accepted[:8] + rejected[:8]


def _obvious_rejects(briefs: list[Brief], run_id: int = 0) -> list[Intersection]:
    if len(briefs) < 2:
        return []
    a, b = briefs[0], briefs[1]
    thesis = f"{a.vertical} × {b.vertical}: generic pairing of today's top headlines"
    return [
        Intersection(
            id=f"r{run_id}-{slug(thesis + '-reject')}",
            verticals=[a.vertical, b.vertical],
            thesis=thesis,
            surprise=0.15,
            plausibility=0.8,
            coverage=Coverage.crowded,
            accepted=False,
            reject_reason="headline-level pairing with no mechanism",
            brief_ids=[a.id, b.id],
            written_by="template",
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
