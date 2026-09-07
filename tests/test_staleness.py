from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from dashboard.main import app
from swarm.db import init_db, session_scope
from swarm.orm import DigestRow, RunRow
from swarm.staleness import digest_age_days, is_stale, last_run_label


def test_age_and_stale_threshold():
    as_of = date(2026, 9, 10)
    assert digest_age_days(date(2026, 9, 10), as_of=as_of) == 0
    assert digest_age_days(date(2026, 9, 7), as_of=as_of) == 3
    assert is_stale(3, 3) is False
    assert is_stale(4, 3) is True
    assert last_run_label(0) == "last run: today"
    assert last_run_label(1) == "last run: 1 day ago"
    assert last_run_label(4) == "last run: 4 days ago"


def test_today_page_names_a_backdated_digest():
    init_db()
    old = date.today() - timedelta(days=9)
    with session_scope() as session:
        run = RunRow(status="completed", budget_usd=5.0, warnings=[], source_health=[], stages=["archive"])
        session.add(run)
        session.flush()
        session.query(DigestRow).filter(DigestRow.date >= old.isoformat()).delete()
        session.add(
            DigestRow(
                run_id=run.id,
                date=old.isoformat(),
                title="old digest",
                markdown="# old",
                top_ids=[],
                curated_count=1,
                killed_count=0,
                rejected_intersection_count=0,
                degraded=False,
                warnings=[],
            )
        )

    client = TestClient(app)
    page = client.get("/")
    assert page.status_code == 200
    assert "last run: 9 days ago" in page.text
    assert "stale" in page.text.lower()
