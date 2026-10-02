"""U4: All lists a two-vertical question once.

Red against a concatenated-per-vertical All: ranks 6/7/8 appear twice.
"""

from fastapi.testclient import TestClient

from dashboard.honesty import bank_groups
from dashboard.main import app
from swarm.db import init_db, session_scope
from swarm.models import Question
from swarm.orm import DigestRow, QuestionRow, RunRow


def test_bank_groups_files_under_each_vertical_all_stays_unique():
    q = Question(
        id="two",
        text="If the hospital's only clerk is also the town's only lender, who staffs the night window?",
        lens="contrarian",
        verticals=["health", "business"],
    )
    groups = {vid: qs for vid, _name, qs in bank_groups([q])}
    assert "health" in groups and "business" in groups
    assert groups["health"][0].id == "two"
    assert groups["business"][0].id == "two"


def test_today_all_lists_two_vertical_question_once():
    init_db()
    with session_scope() as session:
        session.query(DigestRow).delete()
        run = RunRow(status="completed", budget_usd=5)
        session.add(run)
        session.flush()
        rid = run.id
        top_id = f"q-top-{rid}"
        two_id = f"q-two-{rid}"
        session.add(
            DigestRow(
                run_id=rid,
                date="2026-10-01",
                title="bank",
                markdown="# b",
                top_ids=[top_id],
                curated_count=2,
            )
        )
        session.add(
            QuestionRow(
                id=top_id,
                run_id=rid,
                text="Who owns the consent trail when the listener has fluctuating capacity and the agent is always on?",
                lens="contrarian",
                verticals=["ai"],
                status="curated",
                rank=1,
            )
        )
        session.add(
            QuestionRow(
                id=two_id,
                run_id=rid,
                text="If the hospital's only clerk is also the town's only lender, who staffs the night window?",
                lens="second_order",
                verticals=["health", "business"],
                status="curated",
                rank=6,
            )
        )
    page = TestClient(app).get("/")
    assert page.status_code == 200
    all_start = page.text.find('id="bank-all"')
    all_end = page.text.find('data-bank-pane', all_start)
    chunk = page.text[all_start:all_end]
    assert chunk.count(f'data-id="{two_id}"') == 1
    health = page.text[page.text.find('data-bank-pane="health"') :]
    health = health[: health.find("data-bank-pane=\"business\"")]
    business = page.text[page.text.find('data-bank-pane="business"') :]
    assert f'data-id="{two_id}"' in health
    assert f'data-id="{two_id}"' in business
    assert 'data-bank-filter="all"' in page.text
