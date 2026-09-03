"""WO-003. Each test names what goes red against the unfixed / unconstrained code."""

from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from dashboard.main import app
from swarm.agents import correspondent as corr
from swarm.agents.correspondent import (
    NOT_OPERATOR_VOICE,
    assemble_markdown,
    extract_numbers,
    select_question,
    ungrounded_numbers,
    write_issue,
)
from swarm.db import init_db, session_scope
from swarm.orm import BriefRow, DigestRow, IntersectionRow, IssueRow, QuestionRow, RatingRow, RunRow
from swarm.publish_gate import PUBLISH_PATHS, RATED_WEEKS_REQUIRED, publish_gate_open, rated_digest_weeks
from swarm.voice import taste_seed_is_filled, voice_is_filled

DISCLOSURE_SNIPPET = "An agentic system generated this week's question"


def _seed_week(*, stars: int | None = None, as_of: date | None = None) -> str:
    """One curated question whose briefs contain no digits."""
    init_db()
    as_of = as_of or date.today()
    qid = f"corr-{uuid4().hex[:12]}"
    with session_scope() as session:
        session.query(IssueRow).filter(IssueRow.week_ending == as_of.isoformat()).delete()
        session.query(DigestRow).filter(DigestRow.date == as_of.isoformat()).delete()
        run = RunRow(status="completed", budget_usd=5.0, warnings=[], source_health=[], stages=["archive"])
        session.add(run)
        session.flush()
        session.add(
            BriefRow(
                id=f"{qid}-b",
                run_id=run.id,
                vertical="health",
                headline="A maker changed its coupon for a weight-loss drug",
                what_is_happening=(
                    "Clinics that sell the drug for cash are changing how they "
                    "talk about patients staying on it."
                ),
                why_now="The coupon change is in the news this week.",
                who_is_affected="Cash-pay patients and the clinics that booked them as forever revenue.",
                sources=["https://example.com/coupon-change"],
            )
        )
        session.add(
            IntersectionRow(
                id=f"{qid}-i",
                run_id=run.id,
                verticals=["health", "business"],
                thesis=(
                    "Cash-pay clinics are priced as if the patient stays; "
                    "the coupon is what made staying possible."
                ),
                surprise=0.6,
                plausibility=0.7,
                coverage="thin",
                accepted=True,
                brief_ids=[f"{qid}-b"],
            )
        )
        session.add(
            QuestionRow(
                id=qid,
                run_id=run.id,
                text=(
                    "If cash-pay patients drop a weight-loss drug when the coupon ends, "
                    "which clinics are still priced as if those patients stay?"
                ),
                lens="second_order",
                verticals=["health", "business"],
                coverage="thin",
                status="curated",
                rank=1,
                brief_ids=[f"{qid}-b"],
                intersection_id=f"{qid}-i",
                context="The collision is the coupon and the clinic's forever-patient math.",
            )
        )
        session.add(
            DigestRow(
                run_id=run.id,
                date=as_of.isoformat(),
                title=f"digest {as_of.isoformat()}",
                markdown="# d",
                top_ids=[qid],
                curated_count=1,
                killed_count=0,
                rejected_intersection_count=0,
                degraded=False,
                warnings=[],
            )
        )
        if stars is not None:
            session.add(RatingRow(question_id=qid, stars=stars))
    return qid


def _essay_body(markdown: str) -> str:
    """The prose the reader sees — not the metadata header or the word-count footer."""
    start = markdown.find("**The question.**")
    end = markdown.find("## Sources")
    if start < 0:
        return markdown
    return markdown[start:end if end > 0 else None]


def test_ungrounded_number_checker_goes_red_on_unconstrained_prose():
    """This is the assertion an unconstrained 800-word pad fails."""
    source = "Clinics that sell the drug for cash are changing how they talk about staying."
    padded = "The weight-loss market grew 40% last year and now worth $12 billion."
    leaked = ungrounded_numbers(padded, source)
    assert leaked, "unconstrained pad must produce ungrounded numbers"
    assert any("40" in n for n in leaked)
    assert extract_numbers(source) == set()


def test_draft_has_no_ungrounded_numeric_claims():
    """Against an unconstrained writer the ungrounded-number assertion goes red."""
    _seed_week()
    row = write_issue()
    assert row is not None
    source = (
        "If cash-pay patients drop a weight-loss drug when the coupon ends, "
        "which clinics are still priced as if those patients stay? "
        "A maker changed its coupon for a weight-loss drug "
        "Clinics that sell the drug for cash are changing how they "
        "talk about patients staying on it. "
        "The coupon change is in the news this week. "
        "Cash-pay patients and the clinics that booked them as forever revenue. "
        "Cash-pay clinics are priced as if the patient stays; "
        "the coupon is what made staying possible. "
        "The collision is the coupon and the clinic's forever-patient math."
    )
    body = _essay_body(row.markdown)
    assert ungrounded_numbers(body, source) == set()


def test_no_publish_path_exists():
    """Against a module that shipped send/publish this assertion goes red.

    The mechanism is an empty PUBLISH_PATHS and no outbound function — not
    an unused flag.
    """
    assert PUBLISH_PATHS == ()
    assert not hasattr(corr, "publish")
    assert not hasattr(corr, "publish_issue")
    assert not hasattr(corr, "send")
    assert not hasattr(corr, "send_issue")
    srcs = [
        Path("swarm/agents/correspondent.py"),
        Path("swarm/run_correspondent.py"),
        Path("swarm/publish_gate.py"),
        Path("dashboard/main.py"),
    ]
    code = "\n".join(p.read_text(encoding="utf-8") for p in srcs)
    assert "import smtplib" not in code
    assert "import resend" not in code
    assert "/api/issues/publish" not in code
    assert "def publish(" not in code
    assert "def send_issue(" not in code
    assert "published_at" not in IssueRow.__table__.c


def test_selection_rule_stated_when_ratings_absent():
    """Against a silent rank pick this assertion goes red."""
    _seed_week()
    picked = select_question()
    assert picked is not None
    assert picked.rule == "curator_rank"
    row = write_issue()
    assert row is not None
    assert row.selection_rule == "curator_rank"
    assert "Selected by: curator rank" in row.markdown
    assert "Selected by: Operator rating" not in row.markdown


def test_selection_prefers_operator_rating():
    today = date.today()
    _seed_week(stars=None, as_of=today - timedelta(days=1))
    _seed_week(stars=5, as_of=today)
    picked = select_question(as_of=today)
    assert picked is not None
    assert picked.rule == "operator_rating"
    assert picked.stars == 5
    row = write_issue(as_of=today)
    assert "Selected by: Operator rating" in row.markdown


def test_empty_voice_file_marks_draft_honestly():
    """Against a silent generic essay this assertion goes red."""
    assert voice_is_filled() is False
    _seed_week()
    row = write_issue()
    assert row is not None
    assert row.voice_ready is False
    assert NOT_OPERATOR_VOICE in row.markdown
    assert "Not in the Operator's voice" in row.markdown


def test_publish_gate_closed_until_taste_and_rated_weeks():
    assert taste_seed_is_filled() is False
    assert rated_digest_weeks() < RATED_WEEKS_REQUIRED
    assert publish_gate_open() is False
    _seed_week()
    row = write_issue()
    assert row is not None
    assert row.status == "draft"
    assert row.publish_gate_open is False
    assert "Publish gate closed" in row.markdown


def test_issues_page_and_download():
    _seed_week()
    row = write_issue()
    client = TestClient(app)
    listing = client.get("/issues")
    assert listing.status_code == 200
    assert "Draft this week's issue" in listing.text
    assert "Never auto-published" in listing.text or "Nothing here is published" in listing.text
    assert "not in the Operator's voice" in listing.text.lower() or "empty template" in listing.text
    page = client.get(f"/issues/{row.week_ending}")
    assert page.status_code == 200
    assert "Selected by: curator rank" in page.text
    md = client.get(f"/issues/{row.week_ending}.md")
    assert md.status_code == 200
    assert "Selected by: curator rank" in md.text
    assert DISCLOSURE_SNIPPET in md.text


def test_assemble_injects_disclosure_not_the_model():
    """Disclosure is assembled in code. A model that omitted it still has it."""
    _seed_week()
    selection = select_question()
    from swarm.agents.correspondent import load_grounding

    g = load_grounding(selection)
    md = assemble_markdown(
        selection=selection,
        g=g,
        title="t",
        essay="The pairing is in the question itself.",
        warnings=[],
        as_of=date.today(),
    )
    assert DISCLOSURE_SNIPPET in md
