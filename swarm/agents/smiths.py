from __future__ import annotations

from pathlib import Path

from swarm.config import lenses
from swarm.ids import slug
from swarm.llm import LLM
from swarm.models import Brief, Coverage, DecayClass, Intersection, Question, TasteProfile
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
                    "intersection_thesis": {"type": "string"},
                },
                "required": ["text", "verticals", "coverage", "decay_class", "context"],
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
        "What becomes scarce if {a} and {b} keep accelerating on the same calendar?",
        "Which job that looks safe today is actually the buffer that {a} is about to delete?",
    ],
    "opportunity": [
        "What can be built now for the people living between {a} and {b} that could not ship twelve months ago?",
        "Where is the information gap between the operators touched by {a} and the vendors still selling last year's workflow?",
        "Who is the ignored buyer created by {a}, and what is the weekend experiment that would find them?",
    ],
}


def run_smiths(
    briefs: list[Brief],
    intersections: list[Intersection],
    taste: TasteProfile,
    llm: LLM,
) -> list[Question]:
    accepted = [i for i in intersections if i.accepted]
    questions: list[Question] = []
    for lens in lenses():
        produced = _llm(lens, briefs, accepted, taste, llm) or _fallback(
            lens, briefs, accepted
        )
        questions.extend(produced)
    return questions


def _llm(
    lens: dict,
    briefs: list[Brief],
    intersections: list[Intersection],
    taste: TasteProfile,
    llm: LLM,
) -> list[Question] | None:
    if not llm.available:
        return None
    system = PROMPT.format(
        lens_name=lens["name"],
        lens_essence=lens["essence"].strip(),
        taste=profile_for_prompt(taste),
    )
    user_bits = ["BRIEFS:"]
    user_bits.extend(f"- [{b.vertical}] {b.headline}" for b in briefs[:16])
    user_bits.append("INTERSECTIONS:")
    user_bits.extend(
        f"- {' × '.join(i.verticals)} ({i.coverage.value} coverage, surprise={i.surprise:.2f}): {i.thesis}"
        for i in intersections[:10]
    )
    data = llm.complete_json(
        system=system,
        user="\n".join(user_bits),
        schema=SCHEMA,
        max_tokens=4000,
    )
    if not data:
        return None
    out: list[Question] = []
    for raw in data.get("questions") or []:
        try:
            text = raw["text"]
            inter = next(
                (i for i in intersections if i.thesis == raw.get("intersection_thesis")),
                intersections[0] if intersections else None,
            )
            out.append(
                Question(
                    id=f"{lens['id']}-{slug(text)}",
                    text=text,
                    lens=lens["id"],
                    verticals=raw.get("verticals") or (inter.verticals if inter else []),
                    coverage=Coverage(raw.get("coverage") or (inter.coverage.value if inter else "unknown")),
                    decay_class=DecayClass(raw.get("decay_class") or "slow"),
                    brief_ids=inter.brief_ids if inter else [],
                    intersection_id=inter.id if inter else None,
                    context=raw.get("context") or "",
                )
            )
        except Exception:
            continue
    return out or None


def _fallback(
    lens: dict, briefs: list[Brief], intersections: list[Intersection]
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
        )
    ]
    for tmpl, inter in zip(templates, pairs):
        a = _short(inter.thesis)
        b = _other(inter, briefs)
        text = tmpl.format(a=a, b=b)
        out.append(
            Question(
                id=f"{lens['id']}-{slug(text)}",
                text=text,
                lens=lens["id"],
                verticals=inter.verticals,
                coverage=inter.coverage,
                decay_class=DecayClass.slow,
                brief_ids=inter.brief_ids,
                intersection_id=inter.id,
                context=inter.thesis,
            )
        )
    return out


def _short(text: str, n: int = 90) -> str:
    text = text.strip().rstrip(".")
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def _other(inter: Intersection, briefs: list[Brief]) -> str:
    for b in briefs:
        if b.id not in inter.brief_ids:
            return _short(b.headline, 70)
    if len(inter.verticals) > 1:
        return inter.verticals[-1]
    return "the adjacent vertical nobody is staffing"
