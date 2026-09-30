from __future__ import annotations

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
                    "brief_refs": {"type": "array", "items": {"type": "string"}},
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
    return "\n".join(bits)


def run_smiths(
    briefs: list[Brief],
    intersections: list[Intersection],
    taste: TasteProfile,
    llm: LLM,
    *,
    run_id: int = 0,
) -> list[Question]:
    accepted = [i for i in intersections if i.accepted]
    questions: list[Question] = []
    for lens in lenses():
        produced = _llm(lens, briefs, accepted, taste, llm, run_id) or _fallback(
            lens, briefs, accepted, run_id
        )
        questions.extend(produced)
    return questions


def _llm(
    lens: dict,
    briefs: list[Brief],
    intersections: list[Intersection],
    taste: TasteProfile,
    llm: LLM,
    run_id: int,
) -> list[Question] | None:
    if not llm.available:
        return None
    system = PROMPT.format(
        lens_name=lens["name"],
        lens_essence=lens["essence"].strip(),
        taste=profile_for_prompt(taste),
    )
    user = format_smith_block(briefs, intersections)
    data = llm.complete_json(
        system=system,
        user=user,
        schema=SCHEMA,
        max_tokens=4000,
    )
    if not data:
        return None
    label_i = {f"I{i}": inter for i, inter in enumerate(intersections, start=1)}
    label_b = {f"B{i}": brief for i, brief in enumerate(briefs, start=1)}
    writer = llm.writer_name()
    out: list[Question] = []
    for raw in data.get("questions") or []:
        try:
            text = raw["text"]
            ref = str(raw.get("intersection_ref") or "").strip()
            inter = label_i.get(ref)
            if inter is None:
                intersection_id = None
                brief_ids: list[str] = []
                provenance = "unlinked"
                verticals = raw.get("verticals") or []
                coverage = Coverage(raw.get("coverage") or "unknown")
            else:
                intersection_id = inter.id
                brief_ids = []
                for token in raw.get("brief_refs") or []:
                    brief = label_b.get(str(token).strip())
                    if brief and brief.id not in brief_ids:
                        brief_ids.append(brief.id)
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
            continue
    return out or None


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
