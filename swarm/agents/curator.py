from __future__ import annotations

import re
from pathlib import Path

from rapidfuzz import fuzz

from swarm.dedup import normalize
from swarm.llm import LLM
from swarm.models import (
    Coverage,
    DecayClass,
    Question,
    QuestionStatus,
    TasteProfile,
)
from swarm.taste import profile_for_prompt

PROMPT = (Path(__file__).resolve().parent.parent / "prompts" / "curator.md").read_text(
    encoding="utf-8"
)

GENERIC = [
    r"\bimplications of\b",
    r"\bhow will\b.+\baffect\b",
    r"\bopportunities (at|in) the intersection\b",
    r"\bethical concerns\b",
    r"\bis this the year\b",
    r"\bhow can nonprofits use\b",
    r"\bwill (llms|ai) replace\b",
    r"\bfuture of\b.+\?",
]

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "curated": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "rank": {"type": "integer"},
                    "decay_class": {
                        "type": "string",
                        "enum": ["fast", "slow", "evergreen"],
                    },
                    "keep_reason": {"type": "string"},
                },
                "required": ["id", "rank", "decay_class"],
            },
        },
        "killed": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "reason"],
            },
        },
    },
    "required": ["curated", "killed"],
}


def run_curator(
    questions: list[Question], taste: TasteProfile, llm: LLM
) -> list[Question]:
    already = [q for q in questions if q.status == QuestionStatus.duplicate]
    candidates = [q for q in questions if q.status != QuestionStatus.duplicate]
    decided = _llm(candidates, taste, llm)
    if decided is None:
        decided = _fallback(candidates, taste)
    by_id = {q.id: q for q in decided}
    out: list[Question] = []
    for q in questions:
        if q.status == QuestionStatus.duplicate:
            out.append(q)
        elif q.id in by_id:
            out.append(by_id[q.id])
        else:
            q.status = QuestionStatus.killed
            q.kill_reason = q.kill_reason or "not selected by curator"
            out.append(q)
    # Preserve already-listed duplicates that the LLM may have ignored.
    seen = {q.id for q in out}
    for q in already:
        if q.id not in seen:
            out.append(q)
    return out


def _llm(
    candidates: list[Question], taste: TasteProfile, llm: LLM
) -> list[Question] | None:
    if not candidates or not llm.available:
        return None
    system = PROMPT.format(taste=profile_for_prompt(taste))
    lines = [
        f"- id={q.id} lens={q.lens} coverage={q.coverage.value} verts={','.join(q.verticals)} :: {q.text}"
        for q in candidates
    ]
    data = llm.complete_json(
        system=system,
        user="CANDIDATES:\n" + "\n".join(lines),
        schema=SCHEMA,
        reserve=True,
        judgment=True,
        max_tokens=4000,
        estimate_in=4000,
        estimate_out=2000,
    )
    if not data:
        return None
    by_id = {q.id: q for q in candidates}
    curated_ids: set[str] = set()
    for raw in data.get("curated") or []:
        q = by_id.get(raw.get("id", ""))
        if not q:
            continue
        q.status = QuestionStatus.curated
        q.rank = int(raw.get("rank") or 99)
        try:
            q.decay_class = DecayClass(raw.get("decay_class") or "slow")
        except ValueError:
            q.decay_class = DecayClass.slow
        curated_ids.add(q.id)
    for raw in data.get("killed") or []:
        q = by_id.get(raw.get("id", ""))
        if not q or q.id in curated_ids:
            continue
        q.status = QuestionStatus.killed
        q.kill_reason = raw.get("reason") or "killed by curator"
    for q in candidates:
        if q.id not in curated_ids and q.status != QuestionStatus.killed:
            q.status = QuestionStatus.killed
            q.kill_reason = q.kill_reason or "not selected by curator"
    return candidates


def _fallback(candidates: list[Question], taste: TasteProfile) -> list[Question]:
    scored: list[tuple[float, Question]] = []
    for q in candidates:
        score, reason = _score(q, taste)
        if score < 0.42:
            q.status = QuestionStatus.killed
            q.kill_reason = reason
        else:
            q.status = QuestionStatus.curated
            q.kill_reason = ""
        scored.append((score, q))
    curated = [q for s, q in scored if q.status == QuestionStatus.curated]
    curated.sort(key=lambda q: _score(q, taste)[0], reverse=True)
    for i, q in enumerate(curated, start=1):
        q.rank = i
    # Keep a readable bank, not a firehose.
    for extra in curated[16:]:
        extra.status = QuestionStatus.killed
        extra.kill_reason = extra.kill_reason or "below rank cutoff"
        extra.rank = None
    return [q for _, q in scored]


def _score(q: Question, taste: TasteProfile) -> tuple[float, str]:
    text = q.text
    low = text.lower()
    for pat in GENERIC:
        if re.search(pat, low):
            return 0.1, f"generic shape: {pat}"
    if not text.endswith("?") and "?" not in text:
        return 0.25, "not posed as a question"
    if len(text) < 40:
        return 0.2, "too short to be specific"
    if not re.search(r"\b(who|whom|whose|which|if|when|where)\b", low):
        # still allow "what" if it names a mechanism
        if low.startswith("what are the"):
            return 0.15, "seminar opener"

    keep_hit = max(
        (fuzz.token_set_ratio(normalize(text), normalize(ex.question)) for ex in taste.keep_exemplars),
        default=0,
    )
    kill_hit = max(
        (fuzz.token_set_ratio(normalize(text), normalize(ex.question)) for ex in taste.kill_exemplars),
        default=0,
    )
    score = 0.45
    if keep_hit >= 55:
        score += 0.2
    if kill_hit >= 70:
        score -= 0.35
        return max(score, 0.05), "too close to a seeded kill"
    # Prefer named / hyphenated / numeric specificity
    if re.search(r"\d", text):
        score += 0.08
    if re.search(r"\b(who|whose|which)\b", low):
        score += 0.08
    if q.coverage == Coverage.thin:
        score += 0.03  # visible, not promotional
    if q.coverage == Coverage.crowded:
        score -= 0.04
    return min(score, 0.95), "kept"
