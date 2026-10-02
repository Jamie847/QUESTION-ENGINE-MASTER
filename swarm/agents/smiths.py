from __future__ import annotations

import json
from pathlib import Path

from swarm.config import lenses
from swarm.ids import slug
from swarm.llm import LLM
from swarm.models import Brief, Coverage, DecayClass, Intersection, Question, TasteProfile
from swarm.sources.routing import topic
from swarm.taste import profile_for_prompt

PROMPT = (Path(__file__).resolve().parent.parent / "prompts" / "smith.md").read_text(
    encoding="utf-8"
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "text": {"type": "string"},
                    "verticals": {"type": "array", "items": {"type": "string"}},
                    "coverage": {
                        "type": "string",
                        "enum": ["none", "thin", "crowded", "unknown"],
                    },
                    "decay_class": {
                        "type": "string",
                        "enum": ["fast", "slow", "evergreen"],
                    },
                    "context": {"type": "string"},
                    "intersection_ref": {"type": "string"},
                    "brief_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                },
                "required": [
                    "text",
                    "verticals",
                    "coverage",
                    "decay_class",
                    "context",
                    "intersection_ref",
                    "brief_refs",
                ],
            },
        }
    },
    "required": ["questions"],
}

TEMPLATES = {
    "contrarian": [
        "What if the consensus read of {a} is inverted — who is already positioned for the reverse, and what document would prove it?",
        "If {a} stalls rather than compounds, which budgets and headcounts are stranded because they treated it as weather?",
        "Who profits if the story around {a} is mostly a measurement artifact?",
    ],
    "second_order": [
        "If {a} is still true in five years, which unglamorous institution has to absorb the overflow — and is anyone staffing it?",
        "What becomes scarce if {a} and {b} keep moving on the same calendar?",
        "Which job that looks safe today is actually the buffer that {a} is about to delete?",
    ],
    "opportunity": [
        "What can be built now for the people living between {a} and {b} that could not ship twelve months ago?",
        "Where is the information gap between the operators touched by {a} and the vendors still selling last year's workflow?",
        "Who is the ignored buyer created by {a}, and what is the weekend experiment that would find them?",
    ],
}


def select_by_vertical(items: list, limit: int, vertical_of) -> list:
    """Take turns across verticals so a cap cannot drop whoever is last in the list."""
    if limit <= 0 or not items:
        return []
    order: list[str] = []
    buckets: dict[str, list] = {}
    for item in items:
        vertical = vertical_of(item) or "_"
        if vertical not in buckets:
            order.append(vertical)
            buckets[vertical] = []
        buckets[vertical].append(item)
    cursors = {vertical: 0 for vertical in order}
    chosen: list = []
    while len(chosen) < limit:
        progressed = False
        for vertical in order:
            index = cursors[vertical]
            bucket = buckets[vertical]
            if index >= len(bucket):
                continue
            chosen.append(bucket[index])
            cursors[vertical] = index + 1
            progressed = True
            if len(chosen) >= limit:
                break
        if not progressed:
            break
    return chosen


def select_intersections(intersections: list[Intersection], limit: int) -> list[Intersection]:
    """One intersection from each vertical in turn, then repeat, up to `limit`."""
    if limit <= 0 or not intersections:
        return []
    order: list[str] = []
    for inter in intersections:
        for vertical in inter.verticals or ["_"]:
            if vertical not in order:
                order.append(vertical)
    cursors = {vertical: 0 for vertical in order}
    chosen: list[Intersection] = []
    seen: set[str] = set()
    while len(chosen) < limit:
        progressed = False
        for vertical in order:
            while cursors[vertical] < len(intersections):
                inter = intersections[cursors[vertical]]
                cursors[vertical] += 1
                if vertical in (inter.verticals or []) and inter.id not in seen:
                    chosen.append(inter)
                    seen.add(inter.id)
                    progressed = True
                    break
            if len(chosen) >= limit:
                break
        if not progressed:
            break
    return chosen


def prepare_smith_inputs(
    briefs: list[Brief], intersections: list[Intersection]
) -> tuple[list[Brief], list[Intersection]]:
    from swarm.settings import get_settings

    settings = get_settings()
    accepted = [item for item in intersections if item.accepted]
    return (
        select_by_vertical(briefs, settings.smith_briefs_per_lens, lambda brief: brief.vertical),
        select_intersections(accepted, settings.smith_intersections_per_lens),
    )


def coerce_questions(raw) -> tuple[list, str]:
    """Return question objects and a failure reason when the payload cannot be read.

    Run 20 stored `questions` as a string of JSON for two lenses. Iterating that
    string dropped every question and the template filled the lens.
    """
    if isinstance(raw, list):
        return raw, ""
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return [], "empty"
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [], "unreadable"
        if isinstance(parsed, list):
            return parsed, ""
        if isinstance(parsed, dict):
            inner = parsed.get("questions")
            if isinstance(inner, list):
                return inner, ""
            if isinstance(inner, str):
                return coerce_questions(inner)
        return [], "unreadable"
    if raw is None:
        return [], "empty"
    return [], "unreadable"


def format_smith_block(briefs: list[Brief], intersections: list[Intersection]) -> str:
    """Whole briefs, labelled. Smiths cite B1… and I1…; code maps those to ids."""
    bits = ["BRIEFS:"]
    for i, brief in enumerate(briefs, start=1):
        bits.append(
            f"- B{i} [{brief.vertical}] {brief.headline}\n"
            f"  what is happening: {brief.what_is_happening}\n"
            f"  why now: {brief.why_now}\n"
            f"  who is affected: {brief.who_is_affected}"
        )
    if intersections:
        bits.append("INTERSECTIONS:")
        for i, inter in enumerate(intersections, start=1):
            bits.append(
                f"- I{i} {' × '.join(inter.verticals)} "
                f"({inter.coverage.value} coverage, surprise={inter.surprise:.2f}): {inter.thesis}"
            )
        bits.append(
            "Cite intersection_ref as one of I1… or none. Cite brief_refs as B1…. "
            "Do not invent labels."
        )
    else:
        bits.append(
            "No pairings are available this run. Write from the briefs alone. "
            "Set intersection_ref to none."
        )
    return "\n".join(bits)


def run_smiths(
    briefs: list[Brief],
    intersections: list[Intersection],
    taste: TasteProfile,
    llm: LLM,
    *,
    run_id: int = 0,
) -> tuple[list[Question], list[dict]]:
    chosen_briefs, chosen_intersections = prepare_smith_inputs(briefs, intersections)
    questions: list[Question] = []
    reports: list[dict] = []
    for lens in lenses():
        if not llm.available:
            produced = _fallback(lens, chosen_briefs, chosen_intersections, run_id)
            reports.append({"lens": lens["id"], "model_count": 0, "reason": ""})
            questions.extend(produced)
            continue
        produced, reason = _ask(
            lens, chosen_briefs, chosen_intersections, taste, llm, run_id, fewer=False
        )
        if not produced:
            produced, reason = _ask(
                lens,
                chosen_briefs,
                chosen_intersections,
                taste,
                llm,
                run_id,
                fewer=reason == "truncated",
            )
        reports.append(
            {
                "lens": lens["id"],
                "model_count": len(produced),
                "reason": "" if produced else reason,
            }
        )
        questions.extend(produced)
    return questions, reports


def _ask(
    lens: dict,
    briefs: list[Brief],
    intersections: list[Intersection],
    taste: TasteProfile,
    llm: LLM,
    run_id: int,
    *,
    fewer: bool,
) -> tuple[list[Question], str]:
    system = PROMPT.format(
        lens_name=lens["name"],
        lens_essence=lens["essence"].strip(),
        taste=profile_for_prompt(taste),
    )
    user = format_smith_block(briefs, intersections)
    if fewer:
        user += "\n\nThe previous reply was cut off. Return at most 4 questions."
    data = llm.complete_json(
        system=system,
        user=user,
        schema=SCHEMA,
        max_tokens=4000,
    )
    produced, parsed, dropped, reason = _from_payload(lens, briefs, intersections, data, llm, run_id)
    if hasattr(llm, "note_outcome"):
        llm.note_outcome(parsed, dropped)
    return produced, reason


def _from_payload(
    lens: dict,
    briefs: list[Brief],
    intersections: list[Intersection],
    data: dict | None,
    llm: LLM,
    run_id: int,
) -> tuple[list[Question], int, int, str]:
    stop = str(getattr(llm, "last_stop_reason", "") or "")
    if not data:
        reason = "truncated" if stop == "max_tokens" else "unreadable"
        return [], 0, 0, reason
    raw_items, coerce_reason = coerce_questions(data.get("questions"))
    if coerce_reason == "unreadable" or (coerce_reason and stop == "max_tokens"):
        reason = "truncated" if stop == "max_tokens" else "unreadable"
        return [], 0, 0, reason
    label_i = {f"I{i}": inter for i, inter in enumerate(intersections, start=1)}
    label_b = {f"B{i}": brief for i, brief in enumerate(briefs, start=1)}
    writer = llm.writer_name()
    out: list[Question] = []
    dropped = 0
    parsed = 0
    for raw in raw_items:
        if not isinstance(raw, dict):
            dropped += 1
            continue
        parsed += 1
        try:
            text = raw["text"]
            ref = str(raw.get("intersection_ref") or "").strip().upper()
            inter = None if ref in {"", "NONE"} else label_i.get(ref)
            brief_ids = []
            for token in raw.get("brief_refs") or []:
                brief = label_b.get(str(token).strip().upper())
                if brief and brief.id not in brief_ids:
                    brief_ids.append(brief.id)
            if inter is None and not brief_ids:
                intersection_id = None
                provenance = "unlinked"
                verticals = raw.get("verticals") or []
                coverage = Coverage(raw.get("coverage") or "unknown")
            elif inter is None:
                intersection_id = None
                provenance = "linked"
                verticals = raw.get("verticals") or []
                coverage = Coverage(raw.get("coverage") or "unknown")
            else:
                intersection_id = inter.id
                if not brief_ids:
                    brief_ids = list(inter.brief_ids or [])
                provenance = "linked"
                verticals = raw.get("verticals") or inter.verticals
                coverage = Coverage(raw.get("coverage") or inter.coverage.value)
            out.append(
                Question(
                    id=f"r{run_id}-{lens['id']}-{slug(text)}",
                    text=text,
                    lens=lens["id"],
                    verticals=verticals,
                    coverage=coverage,
                    decay_class=DecayClass(raw.get("decay_class") or "slow"),
                    brief_ids=brief_ids,
                    intersection_id=intersection_id,
                    context=raw.get("context") or "",
                    provenance=provenance,
                    written_by=writer,
                )
            )
        except Exception:
            dropped += 1
            continue
    if out:
        return out, parsed, dropped, ""
    if stop == "max_tokens":
        reason = "truncated"
    elif parsed == 0:
        reason = "empty"
    else:
        reason = "invalid"
    return [], parsed, dropped, reason


def _fallback(
    lens: dict, briefs: list[Brief], intersections: list[Intersection], run_id: int
) -> list[Question]:
    templates = TEMPLATES.get(lens["id"], TEMPLATES["opportunity"])
    out: list[Question] = []
    pairs = intersections[: len(templates)] or [
        Intersection(
            id="solo",
            verticals=[briefs[0].vertical] if briefs else ["ai"],
            thesis=briefs[0].headline if briefs else "today",
            surprise=0.4,
            plausibility=0.5,
            coverage=Coverage.unknown,
            brief_ids=[briefs[0].id] if briefs else [],
            written_by="template",
        )
    ]
    used_briefs: set[str] = set()
    for tmpl, inter in zip(templates, pairs):
        related = [b for b in briefs if b.id in (inter.brief_ids or [])]
        a = topic(related[0].headline, words=12) if related else topic(inter.thesis, words=12)
        b = (
            topic(related[1].headline, words=12)
            if len(related) > 1
            else _other_topic(inter, briefs)
        )
        text = tmpl.format(a=a, b=b)
        used_briefs.update(inter.brief_ids or [])
        out.append(
            Question(
                id=f"r{run_id}-{lens['id']}-{slug(text)}",
                text=text,
                lens=lens["id"],
                verticals=inter.verticals,
                coverage=inter.coverage,
                decay_class=DecayClass.slow,
                brief_ids=list(inter.brief_ids or []),
                intersection_id=inter.id,
                context=inter.thesis,
                provenance="linked",
                written_by="template",
            )
        )
    leftovers = [b for b in briefs if b.id not in used_briefs][:3]
    single = templates[0]
    for brief in leftovers:
        a = topic(brief.headline, words=12)
        text = single.format(a=a, b="the adjacent market nobody is staffing")
        out.append(
            Question(
                id=f"r{run_id}-{lens['id']}-{slug(text)}",
                text=text,
                lens=lens["id"],
                verticals=[brief.vertical],
                coverage=Coverage.unknown,
                decay_class=DecayClass.slow,
                brief_ids=[brief.id],
                context=brief.why_now,
                provenance="linked",
                written_by="template",
            )
        )
    return out


def _other_topic(inter: Intersection, briefs: list[Brief]) -> str:
    for b in briefs:
        if b.id not in inter.brief_ids:
            return topic(b.headline, words=8)
    if len(inter.verticals) > 1:
        return inter.verticals[-1]
    return "the adjacent vertical nobody is staffing"
