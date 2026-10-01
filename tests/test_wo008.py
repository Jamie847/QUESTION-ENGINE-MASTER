"""WO-008 empty lenses. Each test names the assertion that is red against unfixed code."""

from __future__ import annotations

import json
from datetime import date

from swarm.agents.archivist import render_digest
from swarm.agents.smiths import format_smith_block, prepare_smith_inputs, run_smiths
from swarm.budget import RunBudget
from swarm.db import init_db, session_scope
from swarm.llm import LLM
from swarm.models import (
    Brief,
    Coverage,
    Intersection,
    Question,
    QuestionStatus,
    SourceHealth,
    TasteProfile,
)
from swarm.orm import AgentCallRow, RunRow

VALID = {
    "text": "Who staffs the overflow if the named docket stalls for the foundries already buying wafers?",
    "verticals": ["ai"],
    "coverage": "thin",
    "decay_class": "slow",
    "context": "The docket.",
    "intersection_ref": "none",
    "brief_refs": [],
}


def _brief(vertical: str, headline: str) -> Brief:
    return Brief(
        id=f"{vertical}-{headline}",
        vertical=vertical,
        headline=headline,
        what_is_happening="A named change on a named date.",
        why_now="The window is open.",
        who_is_affected="the people inside the institution",
    )


def _inter() -> Intersection:
    return Intersection(
        id="i-real",
        verticals=["ai", "business"],
        thesis="The comment window reprices foundry contracts.",
        surprise=0.6,
        plausibility=0.5,
        coverage=Coverage.thin,
        accepted=True,
        brief_ids=["b1"],
    )


def test_l1_stringified_questions_are_kept():
    """Red against iterating the questions string and filling the lens with templates."""
    payload = json.dumps({"questions": [VALID, {**VALID, "text": VALID["text"] + " And who pays?"}]})

    class Fake:
        available = True
        last_stop_reason = "end_turn"

        def writer_name(self, judgment: bool = False) -> str:
            return "model:test-writer"

        def complete_json(self, *, system: str, user: str, schema: dict, **kwargs):
            if "Opportunity" in system:
                return {"questions": payload}
            return {"questions": [VALID]}

    questions, reports = run_smiths([_brief("ai", "NIST counted 12 comments")], [_inter()], TasteProfile(), Fake(), run_id=4)
    opportunity = [q for q in questions if q.lens == "opportunity"]
    assert len(opportunity) == 2
    assert all(q.written_by == "model:test-writer" for q in opportunity)
    assert not any(q.written_by == "template" for q in questions)
    assert next(r for r in reports if r["lens"] == "opportunity")["model_count"] == 2


def test_truncated_reply_retries_once_and_stays_empty():
    """Red against a cut-off reply being replaced by template questions in a keyed run."""
    calls: list[str] = []

    class Fake:
        available = True
        last_stop_reason = "max_tokens"

        def writer_name(self, judgment: bool = False) -> str:
            return "model:test-writer"

        def complete_json(self, *, system: str, user: str, schema: dict, **kwargs):
            if "Opportunity" in system:
                calls.append(user)
                self.last_stop_reason = "max_tokens"
                return {"questions": "{\"questions\":[{\"text\": \"cut"}
            self.last_stop_reason = "end_turn"
            return {"questions": [VALID]}

    questions, reports = run_smiths([_brief("ai", "NIST counted 12 comments")], [_inter()], TasteProfile(), Fake(), run_id=5)
    assert len(calls) == 2
    assert "at most 4" in calls[1]
    assert not any(q.lens == "opportunity" for q in questions)
    assert not any(q.written_by == "template" for q in questions)
    doc = _digest(questions, reports)
    assert "opportunity: no questions (truncated)" in doc


def test_empty_lens_is_named_in_the_header():
    """Red against an empty model array being replaced by templates with no header reason."""

    class Fake:
        available = True
        last_stop_reason = "end_turn"

        def writer_name(self, judgment: bool = False) -> str:
            return "model:test-writer"

        def complete_json(self, *, system: str, user: str, schema: dict, **kwargs):
            if "Second-Order" in system:
                self.last_stop_reason = "end_turn"
                return {"questions": []}
            self.last_stop_reason = "end_turn"
            return {"questions": [VALID]}

    questions, reports = run_smiths([_brief("ai", "NIST counted 12 comments")], [_inter()], TasteProfile(), Fake(), run_id=6)
    assert not any(q.lens == "second_order" for q in questions)
    assert not any(q.written_by == "template" for q in questions)
    assert "second-order: no questions (empty)" in _digest(questions, reports)


def test_keyless_run_keeps_labelled_templates():
    """Red against deleting the template path that local runs still need."""

    class Off:
        available = False

    questions, reports = run_smiths([_brief("ai", "NIST counted 12 comments")], [_inter()], TasteProfile(), Off(), run_id=7)
    assert questions
    assert all(q.written_by == "template" for q in questions)
    assert all(not report["reason"] for report in reports)


def test_bad_label_is_unlinked_not_dropped():
    """Red against discarding a question whose intersection_ref is not in the prompt."""

    class Fake:
        available = True
        last_stop_reason = "end_turn"

        def writer_name(self, judgment: bool = False) -> str:
            return "model:test-writer"

        def complete_json(self, *, system: str, user: str, schema: dict, **kwargs):
            self.last_stop_reason = "end_turn"
            return {"questions": [{**VALID, "intersection_ref": "not-a-label", "brief_refs": ["B9"]}]}

    questions, _reports = run_smiths([_brief("ai", "NIST counted 12 comments")], [_inter()], TasteProfile(), Fake(), run_id=8)
    assert len(questions) == 3
    assert all(q.provenance == "unlinked" for q in questions)
    assert all(q.intersection_id is None for q in questions)
    assert all(q.brief_ids == [] for q in questions)
    assert all(q.written_by == "model:test-writer" for q in questions)


def test_every_vertical_reaches_every_smith_inside_the_cap():
    """Red against sending every brief in list order, and against a prefix that drops the last vertical."""
    verticals = ["ai", "health", "business", "science", "education"]
    briefs = []
    for vertical in verticals:
        for index in range(8):
            headline = f"FIRST-{vertical}" if index == 0 else f"{vertical}-brief-{index}"
            if vertical == "ai" and index == 7:
                headline = "ONLY-EIGHTH-AI"
            briefs.append(_brief(vertical, headline))
    chosen, _intersections = prepare_smith_inputs(briefs, [])
    block = format_smith_block(chosen, [])
    for vertical in verticals:
        assert f"FIRST-{vertical}" in block
    assert "ONLY-EIGHTH-AI" not in block
    assert len(chosen) == 30


def test_call_log_records_stop_reason_and_counts():
    """Red against an agent_calls row that cannot say why the smith stopped or what it parsed."""
    init_db()
    with session_scope() as session:
        run = RunRow(status="completed", budget_usd=5.0, warnings=[], source_health=[], stages=[])
        session.add(run)
        session.flush()
        run_id = run.id
    llm = LLM(RunBudget(1))
    llm.run_id = run_id
    llm.agent = "smiths"
    llm._record_call(
        model="claude-sonnet-5",
        ok=True,
        system="system",
        user="user",
        output="{}",
        error="",
        latency_ms=10,
        stop_reason="max_tokens",
    )
    llm.note_outcome(8, 1)
    with session_scope() as session:
        row = session.get(AgentCallRow, llm.last_call_id)
        assert row is not None
        assert row.stop_reason == "max_tokens"
        assert row.parsed_count == 8
        assert row.dropped_count == 1


def _digest(questions: list[Question], reports: list[dict]) -> str:
    for question in questions:
        question.status = QuestionStatus.curated
        question.rank = 1
    doc = render_digest(
        day=date(2026, 9, 30),
        briefs=[],
        intersections=[],
        questions=questions,
        health=[SourceHealth(source="hacker_news", ok=True, count=1)],
        warnings=[],
        degraded=False,
        cost_usd=1.46,
        lens_reports=reports,
    )
    return doc.markdown
