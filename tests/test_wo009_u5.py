"""U5: near-miss pairs by shared provenance, not shared words.

Red against the unfixed ranker: run 20's unrelated low-overlap pairs
are selected because they share a vertical and the sampler always
returns three.
"""

from fastapi.testclient import TestClient

from dashboard.main import app
from swarm.db import init_db, session_scope
from swarm.dedup import sample_near_miss_pairs
from swarm.models import Brief, Question, QuestionStatus
from swarm.orm import BriefRow, DigestRow, QuestionRow, RunRow


SHARED_URL = "https://www.federalregister.gov/documents/2026/01/15/ed-gainful"


def test_shared_url_with_few_words_is_selected():
    today = [
        Question(
            id="t-sleep",
            text="Who eats the lease when the infusion chairs go dark after the new drugs ship?",
            lens="second_order",
            verticals=["health"],
            status=QuestionStatus.curated,
            brief_ids=["b-rule"],
        )
    ]
    prior = [
        Question(
            id="p-sleep",
            text="Which landlord is still pricing clinic buildouts as if the drip stays forever?",
            lens="contrarian",
            verticals=["business"],
            status=QuestionStatus.curated,
            brief_ids=["b-old"],
        )
    ]
    briefs = {
        "b-rule": Brief(
            id="b-rule",
            vertical="health",
            headline="rule",
            what_is_happening="rule",
            why_now="now",
            who_is_affected="clinics",
            sources=[SHARED_URL],
        ),
        "b-old": Brief(
            id="b-old",
            vertical="health",
            headline="old",
            what_is_happening="old",
            why_now="then",
            who_is_affected="clinics",
            sources=[SHARED_URL],
        ),
    }
    pairs = sample_near_miss_pairs(today, prior, briefs_by_id=briefs)
    assert len(pairs) == 1
    assert pairs[0].share_kind == "url"
    assert pairs[0].score < 0.2


def test_unrelated_low_overlap_is_not_selected():
    today = [
        Question(
            id="t-clerk",
            text="Who staffs the night window when the hospital's only clerk resigns?",
            lens="opportunity",
            verticals=["health"],
            status=QuestionStatus.curated,
            brief_ids=["b1"],
        )
    ]
    prior = [
        Question(
            id="p-foundry",
            text="What breaks first when the foundry queue is the only scarce input left?",
            lens="second_order",
            verticals=["business"],
            status=QuestionStatus.curated,
            brief_ids=["b2"],
        )
    ]
    briefs = {
        "b1": Brief(
            id="b1",
            vertical="health",
            headline="a",
            what_is_happening="a",
            why_now="n",
            who_is_affected="p",
            sources=["https://a.example/1"],
        ),
        "b2": Brief(
            id="b2",
            vertical="business",
            headline="b",
            what_is_happening="b",
            why_now="n",
            who_is_affected="p",
            sources=["https://b.example/2"],
        ),
    }
    assert sample_near_miss_pairs(today, prior, briefs_by_id=briefs) == []


def test_today_shows_no_close_pairs_when_none_qualify():
    init_db()
    with session_scope() as session:
        session.query(DigestRow).delete()
        prior = RunRow(status="completed", budget_usd=5)
        session.add(prior)
        session.flush()
        pid = prior.id
        session.add(
            DigestRow(
                run_id=pid,
                date="2026-09-29",
                title="prior",
                markdown="# p",
                top_ids=[f"p-{pid}"],
                curated_count=1,
            )
        )
        session.add(
            QuestionRow(
                id=f"p-{pid}",
                run_id=pid,
                text="What breaks first when the foundry queue is the only scarce input left?",
                lens="second_order",
                verticals=["business"],
                status="curated",
                rank=1,
                brief_ids=[],
            )
        )
        today = RunRow(status="completed", budget_usd=5)
        session.add(today)
        session.flush()
        tid = today.id
        session.add(
            DigestRow(
                run_id=tid,
                date="2026-09-30",
                title="today",
                markdown="# t",
                top_ids=[f"t-{tid}"],
                curated_count=1,
            )
        )
        session.add(
            QuestionRow(
                id=f"t-{tid}",
                run_id=tid,
                text="Who staffs the night window when the hospital's only clerk resigns in March?",
                lens="opportunity",
                verticals=["health"],
                status="curated",
                rank=1,
                brief_ids=[],
            )
        )
    page = TestClient(app).get("/")
    assert page.status_code == 200
    assert "No close pairs today" in page.text
    assert "near-miss-list" not in page.text
