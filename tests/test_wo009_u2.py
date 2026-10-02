"""U2: curator titles, old rows stay untitled, smith prompt is tight.

Red against the unfixed code: Question has no title, the card renders
the 50–70 word question alone, and smith.md does not cap words or ban
quietly/silently.
"""

from fastapi.testclient import TestClient

from dashboard.main import app
from swarm.agents.curator import clip_title, run_curator, title_from_question
from swarm.budget import RunBudget
from swarm.db import init_db, session_scope
from swarm.llm import LLM
from swarm.models import Coverage, Question, QuestionStatus
from swarm.orm import DigestRow, QuestionRow, RunRow
from swarm.taste import load_seed_profile


def test_title_is_at_most_ten_words():
    long = "Sleep clinics' leftover infusion contracts stranded by the new GLP-1 cash-pay collapse"
    assert len(clip_title(long).split()) == 10
    named = title_from_question(
        "If sleep clinics' leftover infusion contracts are stranded by the new drugs, who eats the lease?"
    )
    assert named
    assert len(named.split()) <= 10
    assert "?" not in named


def test_curator_keep_carries_a_title():
    taste = load_seed_profile()
    llm = LLM(RunBudget(0))
    qs = [
        Question(
            id="good",
            text=(
                "If GLP-1 adherence collapses after 18 months for the cash-pay "
                "cohort, which downstream clinics are priced as if patients stay forever?"
            ),
            lens="second_order",
            verticals=["health", "business"],
            coverage=Coverage.thin,
        )
    ]
    out = run_curator(qs, taste, llm)
    kept = next(q for q in out if q.status == QuestionStatus.curated)
    assert kept.title
    assert len(kept.title.split()) <= 10


def test_card_renders_title_and_old_row_does_not_invent_one():
    init_db()
    with session_scope() as session:
        session.query(DigestRow).delete()
        run = RunRow(status="completed", budget_usd=5)
        session.add(run)
        session.flush()
        rid = run.id
        session.add(
            DigestRow(
                run_id=rid,
                date="2026-10-01",
                title="titles",
                markdown="# t",
                top_ids=[f"q-new-{rid}", f"q-old-{rid}"],
                curated_count=2,
            )
        )
        session.add(
            QuestionRow(
                id=f"q-new-{rid}",
                run_id=rid,
                text="If cash-pay GLP-1 users quit at month 18, which clinics are still priced for forever?",
                title="Sleep clinics' contracts stranded by new drugs",
                lens="second_order",
                verticals=["health"],
                status="curated",
                rank=1,
            )
        )
        session.add(
            QuestionRow(
                id=f"q-old-{rid}",
                run_id=rid,
                text="Who owns the consent trail when the listener has fluctuating capacity and the agent is always on?",
                title="",
                lens="contrarian",
                verticals=["ai"],
                status="curated",
                rank=2,
            )
        )
    page = TestClient(app).get("/")
    assert page.status_code == 200
    assert "Sleep clinics" in page.text
    assert "stranded by new drugs" in page.text
    assert 'class="q-title"' in page.text
    # The old row's question is on the page; no invented title was written for it.
    assert (
        "Who owns the consent trail when the listener has fluctuating capacity"
        in page.text
    )
    # Only one title node — the new row. An invented title would add a second.
    assert page.text.count('class="q-title"') == 1


def test_smith_prompt_caps_words_and_bans_quietly():
    from pathlib import Path

    prompt = (
        Path(__file__).resolve().parent.parent / "swarm" / "prompts" / "smith.md"
    ).read_text(encoding="utf-8")
    assert "45 words" in prompt
    assert "quietly" in prompt
    assert "silently" in prompt
