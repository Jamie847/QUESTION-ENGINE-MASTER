from swarm.db import init_db, session_scope
from swarm.kills import label_for, labelled_kills
from swarm.models import Question, QuestionStatus
from sqlalchemy import select

from swarm.orm import KillReasonRow, RunRow
from swarm.run_daily import _persist_kill_reasons


def test_label_for_maps_mechanism_and_generic():
    assert label_for("The mechanism slot is empty") == "empty_mechanism"
    assert label_for("generic shape: \\bimplications of\\b") == "generic"
    assert label_for("too close to a seeded kill") == "taste_kill"
    assert label_for("not selected by curator") == "curator"


def test_kill_reasons_persist_as_labelled_rows():
    init_db()
    with session_scope() as session:
        run = RunRow(status="completed", budget_usd=5)
        session.add(run)
        session.flush()
        run_id = run.id
    questions = [
        Question(
            id="k1",
            text="What are the implications of AI in healthcare today?",
            lens="opportunity",
            verticals=["ai"],
            status=QuestionStatus.killed,
            kill_reason="The mechanism slot is empty",
        ),
        Question(
            id="k2",
            text="Who pays if the cash-pay GLP-1 cohort leaves in month 18?",
            lens="second_order",
            verticals=["health"],
            status=QuestionStatus.curated,
            rank=1,
        ),
    ]
    _persist_kill_reasons(run_id, questions)
    with session_scope() as session:
        rows = list(
            session.scalars(select(KillReasonRow).where(KillReasonRow.run_id == run_id))
        )
    assert len(rows) == 1
    assert rows[0].label == "empty_mechanism"
    assert labelled_kills(questions)[0][1] == "empty_mechanism"
