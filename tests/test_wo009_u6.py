"""U6: Today order, and ruled labels stay visible.

Red against the unfixed page: the steering line and model-written count
sit next to writer_ok_calls in the header, and near-miss / What we read
are always expanded.
"""

from fastapi.testclient import TestClient
from sqlalchemy import select

from dashboard.main import app
from swarm.db import init_db, session_scope
from swarm.orm import DigestRow, QuestionRow, RunRow, SignalRow


def _seed_today() -> None:
    init_db()
    with session_scope() as session:
        session.query(DigestRow).delete()
        run = RunRow(status="completed", budget_usd=5, cost_usd=1.4)
        session.add(run)
        session.flush()
        rid = run.id
        session.add(
            DigestRow(
                run_id=rid,
                date="2026-10-01",
                title="Order check",
                markdown="# o",
                top_ids=[f"q-top-{rid}"],
                curated_count=1,
                warnings=["writer_ok_calls=12", "writer used Claude (12 calls); volume=claude-sonnet-5"],
            )
        )
        session.add(
            QuestionRow(
                id=f"q-top-{rid}",
                run_id=rid,
                text="Who owns the consent trail when the listener has fluctuating capacity and the agent is always on?",
                lens="contrarian",
                verticals=["ai"],
                coverage="thin",
                status="curated",
                rank=1,
                written_by="model:claude-sonnet-5",
            )
        )
        session.add(
            SignalRow(
                run_id=rid,
                source="hacker_news",
                title="HN one",
                url="https://news.ycombinator.com/item?id=1",
                score=10,
            )
        )


def test_ruled_labels_stay_outside_collapsed_section():
    _seed_today()
    page = TestClient(app).get("/")
    assert page.status_code == 200
    before, after = page.text.split("<details", 1)
    assert "Curator steering by:" in before
    assert "model-written" in before
    assert "coverage (model guess)" in before
    assert "token overlap only" in before
    assert "writer_ok_calls=12" not in before
    assert "writer_ok_calls=12" in after
    assert "Behind the scenes" in page.text
    assert "No close pairs today" in after
    assert "No close pairs today" not in before
    assert "What we read" in after
    assert "What we read" not in before


def test_saved_hidden_when_empty_and_listed_when_present():
    _seed_today()
    with session_scope() as session:
        for row in session.scalars(select(QuestionRow).where(QuestionRow.promoted.is_(True))):
            row.promoted = False
            row.promoted_at = None
    empty = TestClient(app).get("/")
    assert "Saved for ideation" not in empty.text
    with session_scope() as session:
        q = session.scalar(
            select(QuestionRow).where(QuestionRow.id.like("q-top-%"))
        )
        assert q is not None
        q.promoted = True
        from datetime import datetime, timezone

        q.promoted_at = datetime.now(timezone.utc)
    page = TestClient(app).get("/")
    assert "Saved for ideation" in page.text
    assert "/archive?saved=1" in page.text
