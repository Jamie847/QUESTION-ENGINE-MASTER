"""The Correspondent — a weekly essay from the week's best question.

Writes for a reader. Every other agent writes for the system.

Drafts only. Spec §6's "no human-in-the-loop" rule is for the private daily
digest. It does not transfer to a newsletter that carries the Operator's name.
There is no publish function, no email send, no Substack client. Do not add one
to "complete" this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from swarm.budget import RunBudget
from swarm.db import session_scope
from swarm.llm import LLM
from swarm.orm import (
    BriefRow,
    DigestRow,
    IntersectionRow,
    IssueRow,
    QuestionRow,
    RatingRow,
    SignalRow,
)
from swarm.publish_gate import PUBLISH_PATHS, gate_reasons, publish_gate_open
from swarm.settings import get_settings
from swarm.voice import load_voice, voice_is_filled

assert PUBLISH_PATHS == ()  # structurally empty; see publish_gate.py

PROMPT = (Path(__file__).resolve().parent.parent / "prompts" / "correspondent.md").read_text(
    encoding="utf-8"
)

WINDOW_DAYS = 7
DISCLOSURE = (
    "An agentic system generated this week's question. This essay is "
    "AI-assisted. Nothing here is published until Jamie says so."
)
NOT_OPERATOR_VOICE = (
    "Not in the Operator's voice. `content/voice.md` is still the empty "
    "template. This draft uses a standing house voice, not Jamie's."
)

# Factual-looking numbers: 40, 40%, $1.2, 18, 1,000. Not ISO dates (those
# are stripped before the check) and not bare years inside a date.
_NUMBER = re.compile(
    r"(?<![\w.])(?:\$\s*)?\d{1,3}(?:,\d{3})+(?:\.\d+)?%?"
    r"|(?<![\w.])(?:\$\s*)?\d+\.\d+%?"
    r"|(?<![\w.])(?:\$\s*)?\d+%?"
    r"|(?<![\w.])\d+(?![\w-])"
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "essay": {"type": "string"},
    },
    "required": ["title", "essay"],
}


@dataclass
class Grounding:
    question: QuestionRow
    briefs: list[BriefRow] = field(default_factory=list)
    intersection: IntersectionRow | None = None
    signals: list[SignalRow] = field(default_factory=list)
    stars: int | None = None
    digest_date: str = ""

    def source_text(self) -> str:
        parts = [
            self.question.text,
            self.question.context or "",
            self.question.lens,
            " ".join(self.question.verticals or []),
        ]
        if self.intersection:
            parts += [
                self.intersection.thesis or "",
                self.intersection.coverage_notes or "",
                self.intersection.coverage or "",
            ]
        for b in self.briefs:
            parts += [
                b.headline,
                b.what_is_happening,
                b.why_now,
                b.who_is_affected,
                " ".join(b.sources or []),
            ]
        for s in self.signals:
            parts += [s.title, s.url, s.snippet]
        return "\n".join(p for p in parts if p)

    def urls(self) -> list[str]:
        seen: list[str] = []
        for b in self.briefs:
            for u in b.sources or []:
                if isinstance(u, str) and u.startswith("http") and u not in seen:
                    seen.append(u)
        for s in self.signals:
            if s.url and s.url.startswith("http") and s.url not in seen:
                seen.append(s.url)
        return seen

    def thin(self) -> bool:
        body = " ".join(
            [
                self.question.context or "",
                self.intersection.thesis if self.intersection else "",
                *(b.what_is_happening or "" for b in self.briefs),
                *(b.why_now or "" for b in self.briefs),
            ]
        )
        return len(body.split()) < 40 and not self.urls()


@dataclass
class Selection:
    question: QuestionRow
    rule: str
    note: str
    stars: int | None
    digest_date: str


# House words the assembler injects. Not claims about the world.
_NAME_STOP = {
    "a",
    "an",
    "and",
    "but",
    "correspondent",
    "draft",
    "if",
    "jamie",
    "operator",
    "selected",
    "sources",
    "the",
    "this",
    "that",
    "we",
    "what",
    "when",
    "which",
    "why",
}

_MULTI_NAME = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
_SINGLE_NAME = re.compile(r"\b([A-Z][a-z]{2,})\b")


def extract_numbers(text: str) -> set[str]:
    cleaned = re.sub(r"\d{4}-\d{2}-\d{2}", "", text)
    return {m.group(0).replace(" ", "") for m in _NUMBER.finditer(cleaned)}


def extract_proper_nouns(text: str) -> set[str]:
    """Multi-word names plus mid-sentence capitalized words.

    Sentence-initial 'The' / 'If' are dropped. Against an unconstrained
    writer, 'Novo Nordisk' and 'Pfizer' land here.
    """
    names: set[str] = set()
    covered: set[str] = set()
    for m in _MULTI_NAME.finditer(text):
        phrase = m.group(1)
        names.add(phrase)
        covered.update(phrase.split())
    for sent in re.split(r"[.!?]\s+", text):
        rest = sent.split(None, 1)
        tail = rest[1] if len(rest) > 1 else ""
        for m in _SINGLE_NAME.finditer(tail):
            word = m.group(1)
            if word.lower() not in _NAME_STOP and word not in covered:
                names.add(word)
    return names


def ungrounded_numbers(essay: str, source: str) -> set[str]:
    """Numeric tokens in the essay that are not in the grounding pack.

    Against an unconstrained 800-word pad this set is non-empty and the
    fabrication test goes red.
    """
    return extract_numbers(essay) - extract_numbers(source)


def ungrounded_names(essay: str, source: str) -> set[str]:
    """Proper nouns in the essay that do not appear in the source pack."""
    src = source.lower()
    return {n for n in extract_proper_nouns(essay) if n.lower() not in src}


def ungrounded_claims(essay: str, source: str) -> set[str]:
    return ungrounded_numbers(essay, source) | ungrounded_names(essay, source)


def drop_ungrounded_sentences(essay: str, source: str) -> tuple[str, int]:
    parts = re.split(r"(?<=[.!?])\s+", essay.strip())
    kept: list[str] = []
    dropped = 0
    for part in parts:
        if ungrounded_claims(part, source):
            dropped += 1
            continue
        kept.append(part)
    return (" ".join(kept).strip(), dropped)


def select_question(*, as_of: date | None = None) -> Selection | None:
    as_of = as_of or date.today()
    start = (as_of - timedelta(days=WINDOW_DAYS - 1)).isoformat()
    end = as_of.isoformat()
    with session_scope() as session:
        q_rows = list(
            session.scalars(
                select(QuestionRow)
                .join(DigestRow, DigestRow.run_id == QuestionRow.run_id)
                .where(QuestionRow.status == "curated")
                .where(DigestRow.date >= start)
                .where(DigestRow.date <= end)
            ).all()
        )
        if not q_rows:
            return None
        ratings = {
            r.question_id: r.stars
            for r in session.scalars(
                select(RatingRow).where(RatingRow.question_id.in_([q.id for q in q_rows]))
            )
        }
        dates = {
            d.run_id: d.date
            for d in session.scalars(
                select(DigestRow).where(DigestRow.run_id.in_({q.run_id for q in q_rows}))
            )
        }
        for q in q_rows:
            session.expunge(q)

    if ratings:
        chosen = max(
            q_rows,
            key=lambda q: (
                ratings.get(q.id, -1),
                -((q.rank or 99)),
                dates.get(q.run_id, ""),
            ),
        )
        stars = ratings[chosen.id]
        return Selection(
            question=chosen,
            rule="operator_rating",
            note=f"Selected by: Operator rating ({stars}★).",
            stars=stars,
            digest_date=dates.get(chosen.run_id, ""),
        )
    chosen = min(q_rows, key=lambda q: (q.rank if q.rank is not None else 99, q.id))
    return Selection(
        question=chosen,
        rule="curator_rank",
        note="Selected by: curator rank (no Operator ratings this week).",
        stars=None,
        digest_date=dates.get(chosen.run_id, ""),
    )


def load_grounding(selection: Selection) -> Grounding:
    q = selection.question
    with session_scope() as session:
        q = session.get(QuestionRow, q.id) or q
        briefs = []
        if q.brief_ids:
            briefs = list(
                session.scalars(select(BriefRow).where(BriefRow.id.in_(list(q.brief_ids)))).all()
            )
        inter = session.get(IntersectionRow, q.intersection_id) if q.intersection_id else None
        urls = []
        for b in briefs:
            urls.extend(u for u in (b.sources or []) if isinstance(u, str))
        signals: list[SignalRow] = []
        if urls:
            signals = list(
                session.scalars(
                    select(SignalRow)
                    .where(SignalRow.run_id == q.run_id)
                    .where(SignalRow.url.in_(urls))
                ).all()
            )
        for row in (*briefs, *signals, q):
            session.expunge(row)
        if inter:
            session.expunge(inter)
    return Grounding(
        question=q,
        briefs=briefs,
        intersection=inter,
        signals=signals,
        stars=selection.stars,
        digest_date=selection.digest_date,
    )


def _pack_for_prompt(g: Grounding) -> str:
    lines = [
        f"QUESTION: {g.question.text}",
        f"LENS: {g.question.lens}",
        f"VERTICALS: {', '.join(g.question.verticals or [])}",
    ]
    if g.question.context:
        lines.append(f"SMITH CONTEXT: {g.question.context}")
    if g.intersection:
        lines.append(f"INTERSECTION THESIS: {g.intersection.thesis}")
        if g.intersection.coverage_notes:
            lines.append(f"COVERAGE NOTES: {g.intersection.coverage_notes}")
        lines.append(f"COVERAGE: {g.intersection.coverage}")
    if not g.briefs:
        lines.append("BRIEFS: none persisted for this question. Stay short. Do not invent.")
    for b in g.briefs:
        lines += [
            f"BRIEF [{b.vertical}] {b.headline}",
            f"  happening: {b.what_is_happening}",
            f"  why now: {b.why_now}",
            f"  who: {b.who_is_affected}",
            f"  urls: {', '.join(b.sources or []) or 'none'}",
        ]
    for s in g.signals:
        lines.append(f"SIGNAL {s.source}: {s.title} — {s.snippet} ({s.url})")
    if g.thin():
        lines.append(
            "GROUNDING IS THIN. Write fewer words. End on what we do not know. "
            "Do not fill the gap."
        )
    return "\n".join(lines)


def _heuristic_essay(g: Grounding) -> str:
    """Grounded only. No figures that are not already in the pack."""
    verts = g.question.verticals or []
    if len(verts) >= 2:
        collide = f"{verts[0]} and {verts[1]}"
    elif verts:
        collide = verts[0]
    else:
        collide = "the domains the curator kept"
    thesis = (
        g.intersection.thesis
        if g.intersection and g.intersection.thesis
        else "The pairing is in the question itself; the briefs do not add a thesis."
    )
    happening = []
    for b in g.briefs:
        bit = " ".join(x for x in (b.headline, b.what_is_happening) if x)
        if bit:
            happening.append(bit)
    watch = []
    for b in g.briefs:
        if b.headline:
            watch.append(b.headline)
    for s in g.signals:
        if s.title and s.title not in watch:
            watch.append(s.title)
    happening_txt = " ".join(happening) if happening else "The persisted briefs are thin."
    watch_txt = (
        "Watch the source list below — if those pages move, the question moves."
        if watch
        else "There is nothing extra to watch beyond the question itself."
    )
    unknown = (
        "We do not know whether the collision holds. The question is the product; "
        "a confident answer would be a guess."
        if g.thin()
        else "What would have to be true is that the people named in the briefs "
        "actually sit at this intersection, and that the mechanism in the question "
        "is the one doing the work. That is not shown yet."
    )
    return (
        f"The question is {g.question.text} It sits where {collide} meet.\n\n"
        f"Why it is not obvious: {thesis} A smart generalist writing a recap "
        f"would have stopped at the headlines. The question keeps going.\n\n"
        f"What the sources actually say: {happening_txt}\n\n"
        f"{unknown}\n\n"
        f"{watch_txt}\n\n"
        f"We do not have to answer it this week."
    )


def _llm_essay(g: Grounding, llm: LLM, voice: str) -> dict[str, str] | None:
    voice_note = (
        f"OPERATOR VOICE (write toward this):\n{voice}"
        if voice
        else "VOICE FILE IS EMPTY. Write plain. Do not impersonate Jamie."
    )
    user = f"{voice_note}\n\nGROUNDING PACK — facts only from here:\n{_pack_for_prompt(g)}"
    data = llm.complete_json(
        system=PROMPT,
        user=user,
        schema=SCHEMA,
        max_tokens=4096,
        estimate_in=2000,
        estimate_out=1200,
        judgment=False,
    )
    if not data or not isinstance(data.get("essay"), str):
        return None
    return {"title": str(data.get("title") or "").strip(), "essay": data["essay"].strip()}


def assemble_markdown(
    *,
    selection: Selection,
    g: Grounding,
    title: str,
    essay: str,
    warnings: list[str],
    as_of: date,
) -> str:
    voice_ok = voice_is_filled()
    gate_ok = publish_gate_open()
    reasons = gate_reasons()
    source = g.source_text()
    essay, dropped = drop_ungrounded_sentences(essay, source)
    if dropped:
        warnings.append(
            f"removed {dropped} sentence(s) whose figures were not in the grounding pack"
        )
    leftover = ungrounded_claims(essay, source)
    if leftover:
        warnings.append(f"ungrounded claims still present after filter: {sorted(leftover)}")
        essay = re.sub(_NUMBER, "", essay)
        essay = re.sub(r"\s{2,}", " ", essay).strip()

    words = len(re.findall(r"[A-Za-z']+", essay))
    lines = [
        f"# {title}",
        "",
        f"_{DISCLOSURE}_",
        "",
        f"**Draft. Not published.** {selection.note}",
        "",
    ]
    if not voice_ok:
        lines += [f"> **{NOT_OPERATOR_VOICE}**", ""]
    if not gate_ok:
        lines += [
            "> **Publish gate closed.** "
            + " ".join(reasons)
            + " Spec §6's no-approval rule is for the digest, not this.",
            "",
        ]
    if g.thin():
        lines += [
            "> **Grounding is thin.** The essay is short on purpose. "
            "The question does not contain 800 words of substance.",
            "",
        ]
    lines += [
        f"**The question.** {g.question.text}",
        "",
        essay,
        "",
        "## Sources",
        "",
    ]
    urls = g.urls()
    if urls:
        for u in urls:
            lines.append(f"- {u}")
    else:
        lines.append("- No source URLs were persisted on this question's briefs.")
    lines += [
        "",
        f"_Week ending {as_of.isoformat()}. {words} words. "
        f"Selection rule: {selection.rule}. Draft only._",
        "",
    ]
    if warnings:
        lines += ["## Draft notes", ""]
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")
    return "\n".join(lines)


def write_issue(*, as_of: date | None = None, llm: LLM | None = None) -> IssueRow | None:
    as_of = as_of or date.today()
    warnings: list[str] = []
    selection = select_question(as_of=as_of)
    if selection is None:
        return None
    g = load_grounding(selection)
    if g.thin():
        warnings.append("grounding thin — briefs/intersection/snippets are short")

    settings = get_settings()
    writer = llm or LLM(RunBudget(min(1.50, settings.budget_usd)))
    voice = load_voice()
    title = f"The Correspondent — week ending {as_of.isoformat()}"
    essay = ""
    if writer.available:
        got = _llm_essay(g, writer, voice)
        if got:
            title = got["title"] or title
            essay = got["essay"]
        else:
            warnings.append("model call failed; used grounded heuristic")
            essay = _heuristic_essay(g)
    else:
        warnings.append("ANTHROPIC_API_KEY unset — grounded heuristic writer")
        essay = _heuristic_essay(g)

    markdown = assemble_markdown(
        selection=selection,
        g=g,
        title=title,
        essay=essay,
        warnings=warnings,
        as_of=as_of,
    )
    words = len(re.findall(r"[A-Za-z']+", essay))
    with session_scope() as session:
        existing = session.scalar(select(IssueRow).where(IssueRow.week_ending == as_of.isoformat()))
        if existing:
            session.delete(existing)
            session.flush()
        row = IssueRow(
            week_ending=as_of.isoformat(),
            question_id=selection.question.id,
            selection_rule=selection.rule,
            selection_note=selection.note,
            title=title,
            markdown=markdown,
            word_count=words,
            voice_ready=voice_is_filled(),
            publish_gate_open=publish_gate_open(),
            status="draft",
            warnings=warnings,
            source_urls=g.urls(),
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
        return row
