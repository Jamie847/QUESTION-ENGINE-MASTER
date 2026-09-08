"""Same-day second run must not replace the first digest (CP 2026-09-08)."""

from datetime import date

from sqlalchemy import select

from swarm.agents.archivist import render_digest
from swarm.db import init_db, session_scope
from swarm.models import Question, QuestionStatus, SourceHealth
from swarm.orm import DigestRow, RunRow
from swarm.run_daily import _persist_digest


def _doc(text: str):
    q = Question(
        id=f"q-{text}",
        text=f"Who pays if {text} fails the mechanism test on a named counterparty?",
        lens="contrarian",
        verticals=["ai"],
        status=QuestionStatus.curated,
        rank=1,
    )
    return render_digest(
        day=date(2026, 9, 8),
        briefs=[],
        intersections=[],
        questions=[q],
        health=[SourceHealth(source="hacker_news", ok=True, count=1)],
        warnings=[],
        degraded=False,
        cost_usd=1.10,
    )


def test_second_same_day_run_keeps_first_digest():
    init_db()
    with session_scope() as session:
        a = RunRow(status="completed", budget_usd=5)
        b = RunRow(status="completed", budget_usd=5)
        session.add_all([a, b])
        session.flush()
        id_a, id_b = a.id, b.id
    _persist_digest(id_a, _doc("run-a"))
    _persist_digest(id_b, _doc("run-b"))
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(DigestRow)
                .where(DigestRow.run_id.in_([id_a, id_b]))
                .order_by(DigestRow.id)
            )
        )
        assert len(rows) == 2
        by_run = {r.run_id: r for r in rows}
        assert id_a in by_run
        assert id_b in by_run
        assert by_run[id_a].date == by_run[id_b].date == "2026-09-08"
        assert "run-a" in by_run[id_a].markdown
        assert "run-b" in by_run[id_b].markdown

    from fastapi.testclient import TestClient

    from dashboard.main import app

    page = TestClient(app).get("/archive")
    assert page.status_code == 200
    assert f"/digest/run/{id_a}" in page.text
    assert f"/digest/run/{id_b}" in page.text
    first = TestClient(app).get(f"/digest/run/{id_a}")
    second = TestClient(app).get(f"/digest/run/{id_b}")
    assert first.status_code == 200
    assert second.status_code == 200
    assert "run-a" in first.text
    assert "run-b" in second.text


def test_resume_rewrites_same_run_digest_only():
    init_db()
    with session_scope() as session:
        run = RunRow(status="completed", budget_usd=5)
        session.add(run)
        session.flush()
        run_id = run.id
    _persist_digest(run_id, _doc("first"))
    _persist_digest(run_id, _doc("second"))
    with session_scope() as session:
        rows = list(session.scalars(select(DigestRow).where(DigestRow.run_id == run_id)))
        assert len(rows) == 1
        assert "second" in rows[0].markdown
