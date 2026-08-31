from datetime import date

from swarm.agents.archivist import render_digest
from swarm.agents.curator import run_curator
from swarm.budget import RunBudget
from swarm.llm import LLM
from swarm.models import (
    Coverage,
    Intersection,
    Question,
    QuestionStatus,
    SourceHealth,
)
from swarm.taste import load_seed_profile


def test_curator_kills_generic_shapes():
    taste = load_seed_profile()
    llm = LLM(RunBudget(0))  # force heuristic path
    qs = [
        Question(
            id="bad",
            text="What are the implications of AI in healthcare today and tomorrow?",
            lens="opportunity",
            verticals=["ai", "health"],
        ),
        Question(
            id="good",
            text="If GLP-1 adherence collapses after 18 months for the cash-pay cohort, which downstream clinics are priced as if patients stay forever?",
            lens="second_order",
            verticals=["health", "business"],
            coverage=Coverage.thin,
        ),
    ]
    out = run_curator(qs, taste, llm)
    by_id = {q.id: q for q in out}
    assert by_id["bad"].status == QuestionStatus.killed
    assert by_id["good"].status == QuestionStatus.curated


def test_digest_includes_rejects_and_coverage():
    q = Question(
        id="q1",
        text="Who owns the consent trail when the listener has fluctuating capacity and the agent is always on?",
        lens="contrarian",
        verticals=["ai", "health"],
        coverage=Coverage.thin,
        status=QuestionStatus.curated,
        rank=1,
        context="Voice agents in eldercare.",
    )
    killed = Question(
        id="q2",
        text="What are the implications of AI in healthcare for everyone involved here?",
        lens="opportunity",
        verticals=["ai"],
        status=QuestionStatus.killed,
        kill_reason="generic shape",
    )
    accepted = Intersection(
        id="i1",
        verticals=["ai", "health"],
        thesis="Consent and capacity collide when the interface is a speaker.",
        surprise=0.7,
        plausibility=0.6,
        coverage=Coverage.thin,
        accepted=True,
    )
    rejected = Intersection(
        id="i2",
        verticals=["ai", "health"],
        thesis="AI scribes for doctors",
        surprise=0.1,
        plausibility=0.9,
        coverage=Coverage.crowded,
        accepted=False,
        reject_reason="already a genre",
    )
    doc = render_digest(
        day=date(2026, 8, 31),
        briefs=[],
        intersections=[accepted, rejected],
        questions=[q, killed],
        health=[SourceHealth(source="hacker_news", ok=True, count=12)],
        warnings=[],
        degraded=False,
        cost_usd=0.0,
    )
    assert "coverage **thin**" in doc.markdown
    assert "Cross-pollinator passed over" in doc.markdown
    assert "already a genre" in doc.markdown
    assert "generic shape" in doc.markdown
    assert doc.rejected_intersection_count == 1
