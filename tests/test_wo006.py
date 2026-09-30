"""WO-006 honesty. Each test names the assertion that is red against unfixed code."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text

from dashboard.main import app
from swarm.agents.scout import format_signal_block, urls_from_model
from swarm.agents.smiths import format_smith_block, run_smiths
from swarm.db import get_engine, init_db, session_scope
from swarm.display_time import digest_local_date, format_run_stamp
from swarm.models import Brief, Coverage, Intersection, Signal, TasteProfile
from swarm.orm import BriefRow, DigestRow, QuestionRow, RatingRow, RunRow
from swarm.ranking import select_round_robin
from swarm.settings import get_settings
from swarm.taste import load_taste, profile_for_prompt, steering_label


def test_f1_unknown_label_is_unlinked_and_scout_drops_invented_urls():
    """Red against smiths that default to intersections[0], and scouts that store model URLs."""
    brief = Brief(
        id="b1",
        vertical="ai",
        headline="NIST published 42 comments on the chip rule",
        what_is_happening="A docket moved on a named date.",
        why_now="The comment window closes Friday.",
        who_is_affected="foundries and the firms buying wafers",
        sources=["https://example.test/nist"],
    )
    inter = Intersection(
        id="i-real",
        verticals=["ai", "business"],
        thesis="The comment window reprices foundry contracts.",
        surprise=0.6,
        plausibility=0.5,
        coverage=Coverage.thin,
        accepted=True,
        brief_ids=["b1"],
    )
    seen: dict[str, str] = {}

    class FakeLLM:
        available = True

        def writer_name(self, judgment: bool = False) -> str:
            return "model:test-writer"

        def complete_json(self, *, system: str, user: str, schema: dict, **kwargs):
            seen[system] = user
            if "Contrarian" in system:
                return None
            return {
                "questions": [
                    {
                        "text": "If the named agency published the number on that date, who absorbs the overflow staffing?",
                        "verticals": ["ai"],
                        "coverage": "thin",
                        "decay_class": "slow",
                        "context": "The docket, not a neighbour intersection.",
                        "intersection_ref": "not-a-label",
                        "brief_refs": ["B9"],
                    }
                ]
            }

    questions = run_smiths([brief], [inter], TasteProfile(), FakeLLM(), run_id=1)
    model_written = [q for q in questions if q.written_by == "model:test-writer"]
    templates = [q for q in questions if q.lens == "contrarian"]
    assert model_written, "expected model questions from the non-contrarian lenses"
    for question in model_written:
        assert question.intersection_id is None
        assert question.brief_ids == []
        assert question.provenance == "unlinked"
    assert templates and all(q.written_by == "template" for q in templates)
    assert any("who is affected: foundries and the firms buying wafers" in body for body in seen.values())

    kept = Signal(
        source="hacker_news",
        title="A counted filing",
        url="https://kept.example/a",
        snippet="The agency counted 12 cases on 2026-01-02.",
    )
    urls = urls_from_model(
        {
            "signal_refs": ["S1"],
            "source_urls": ["https://invented.example/nope", "https://kept.example/a"],
        },
        {"S1": kept},
    )
    assert urls == ["https://kept.example/a"]


def test_f2_round_robin_keeps_a_low_score_source_inside_eighteen_slots():
    """Red against taking the global top 18 by raw score. Call the selector with limit 18."""
    signals: list[Signal] = []
    for i in range(20):
        signals.append(
            Signal(
                source="hacker_news",
                title=f"hn item number {i} is long enough to rank",
                url=f"https://hn.example/{i}",
                score=float(300 - i),
            )
        )
    for i in range(5):
        signals.append(
            Signal(
                source="federal_register",
                title=f"fr item number {i} is a primary document",
                url=f"https://fr.example/{i}",
                score=1.1,
            )
        )
    chosen = select_round_robin(signals, 18)
    assert any(sig.source == "federal_register" for sig, _rank in chosen)
    block = format_signal_block(chosen[:1], snippet_chars=800)
    assert "rank 1" in block
    assert "score=" not in block


def test_f3_template_card_is_labelled(monkeypatch):
    """Red against a template question rendered with no visible template tag."""
    _clear("wo006-template-q")
    started = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)
    with session_scope() as session:
        run = RunRow(
            status="completed",
            budget_usd=5.0,
            cost_usd=0.1,
            started_at=started,
            finished_at=started,
            warnings=[],
            source_health=[],
            stages=["archive"],
            curated_by="template",
        )
        session.add(run)
        session.flush()
        session.add(
            QuestionRow(
                id="wo006-template-q",
                run_id=run.id,
                text="What if the consensus read of the named docket is inverted for the foundries already positioned?",
                lens="contrarian",
                verticals=["ai"],
                coverage="thin",
                status="curated",
                rank=1,
                provenance="linked",
                written_by="template",
                brief_ids=[],
            )
        )
        session.add(
            DigestRow(
                run_id=run.id,
                date="2026-09-30",
                title="template label",
                markdown="# template",
                top_ids=["wo006-template-q"],
                curated_count=1,
                killed_count=0,
                rejected_intersection_count=0,
                degraded=False,
                warnings=[],
            )
        )
    page = TestClient(app).get("/")
    article = _article(page.text, "wo006-template-q")
    assert "template" in article
    assert "coverage (model guess)" in article


def test_f3_keyed_curator_failure_writes_no_digest(monkeypatch):
    """Red against archiving a heuristic curator after a keyed call returns nothing."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("ALLOW_DEMO_SIGNALS", "false")
    get_settings.cache_clear()

    async def one_signal(_sources):
        from swarm.models import SourceHealth

        signal = Signal(
            source="hacker_news",
            title="NIST counted 12 comments on a named docket",
            url="https://news.example/nist",
            snippet="Twelve comments, one agency, one date.",
            score=4.0,
            vertical_hints=["ai"],
        )
        return [signal], [SourceHealth(source="hacker_news", ok=True, count=1)]

    def no_json(self, **kwargs):
        return None

    monkeypatch.setattr("swarm.run_daily.collect_signals", one_signal)
    monkeypatch.setattr("swarm.llm.LLM.complete_json", no_json)
    from swarm.run_daily import main as swarm_main

    code = swarm_main(["--force"])
    assert code == 1
    with session_scope() as session:
        run = session.scalar(select(RunRow).order_by(RunRow.id.desc()))
        assert run is not None
        assert run.status == "failed"
        assert "CuratorFallback" in (run.error or "")
        digest = session.scalar(select(DigestRow).where(DigestRow.run_id == run.id))
        assert digest is None
    get_settings.cache_clear()


def test_f4_all_sources_dark_fails_without_a_digest(monkeypatch):
    """Red against substituting the GLP-1 demo signals when every source is empty."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("ALLOW_DEMO_SIGNALS", "false")
    get_settings.cache_clear()

    async def empty(_sources):
        return [], []

    monkeypatch.setattr("swarm.run_daily.collect_signals", empty)
    from swarm.run_daily import main as swarm_main

    code = swarm_main(["--force"])
    assert code == 1
    with session_scope() as session:
        run = session.scalar(select(RunRow).order_by(RunRow.id.desc()))
        assert run is not None
        assert run.status == "failed"
        assert "all sources dark" in (run.error or "")
        digest = session.scalar(select(DigestRow).where(DigestRow.run_id == run.id))
        assert digest is None
    get_settings.cache_clear()


def test_f5_stand_in_is_labelled_until_ratings_cross_the_threshold():
    """Red against an unlabelled hardcoded taste lead, and against ignoring Operator ratings."""
    init_db()
    client = TestClient(app)
    before = client.get("/taste")
    assert before.status_code == 200
    assert "stand-in seed" in before.text
    assert "not the Operator" in before.text
    try:
        with session_scope() as session:
            run = RunRow(status="completed", budget_usd=5.0, warnings=[], source_health=[], stages=[])
            session.add(run)
            session.flush()
            for i in range(5):
                session.add(
                    QuestionRow(
                        id=f"wo006-rate-k{i}",
                        run_id=run.id,
                        text=f"RATING-KEEP-UNIQUE-ZEBRA keep number {i} names a mechanism and a population",
                        lens="contrarian",
                        verticals=["ai"],
                        status="curated",
                    )
                )
                session.add(
                    QuestionRow(
                        id=f"wo006-rate-x{i}",
                        run_id=run.id,
                        text=f"RATING-KILL-UNIQUE-ZEBRA kill number {i} is a seminar title about implications",
                        lens="opportunity",
                        verticals=["ai"],
                        status="killed",
                    )
                )
            session.flush()
            for i in range(5):
                session.add(RatingRow(question_id=f"wo006-rate-k{i}", stars=5, why=f"keep why {i}"))
                session.add(RatingRow(question_id=f"wo006-rate-x{i}", stars=1, why=f"kill why {i}"))
        profile, source = load_taste()
        prompt = profile_for_prompt(profile)
        assert source == "operator-ratings"
        assert "RATING-KEEP-UNIQUE-ZEBRA" in prompt
        assert "fluctuating capacity" not in prompt
        page = client.get("/taste")
        assert "Curator steering by: Operator ratings" in page.text
        assert "RATING-KEEP-UNIQUE-ZEBRA" in page.text
    finally:
        with session_scope() as session:
            session.execute(delete(RatingRow).where(RatingRow.question_id.like("wo006-rate-%")))
            session.execute(delete(QuestionRow).where(QuestionRow.id.like("wo006-rate-%")))
        assert steering_label() == "Curator steering by: stand-in seed (not the Operator's)"


def test_f6_promote_keeps_status_and_rank():
    """Red against promote rewriting a killed question to curated rank 50."""
    _clear("wo006-promote-q")
    with session_scope() as session:
        run = RunRow(status="completed", budget_usd=5.0, warnings=[], source_health=[], stages=[])
        session.add(run)
        session.flush()
        session.add(
            QuestionRow(
                id="wo006-promote-q",
                run_id=run.id,
                text="Who staffs the overflow if the named docket stalls for the foundries?",
                lens="second_order",
                verticals=["ai"],
                status="killed",
                rank=7,
                kill_reason="generic shape",
                promoted=False,
            )
        )
    client = TestClient(app)
    resp = client.post("/api/questions/wo006-promote-q/promote")
    assert resp.status_code == 200
    with session_scope() as session:
        row = session.get(QuestionRow, "wo006-promote-q")
        assert row is not None
        assert row.status == "killed"
        assert row.rank == 7
        assert row.promoted is True
        assert row.promoted_at is not None
    saved = client.get("/archive?saved=1")
    assert "Who staffs the overflow" in saved.text
    assert "Saved — ideation not built yet." in saved.text


def test_f7_denver_stamp_and_digest_date():
    """Red against printing the UTC calendar date for a run that is still Tuesday in Denver."""
    started = datetime(2026, 9, 30, 2, 30, tzinfo=timezone.utc)
    stamp = format_run_stamp(started, "America/Denver")
    assert "Sep 29, 8:30 PM MDT" in stamp
    assert digest_local_date(started, "America/Denver").isoformat() == "2026-09-29"


def test_f7_today_page_uses_display_tz(monkeypatch):
    """Red against a Today header that shows 2026-09-30 for this instant in America/Denver."""
    monkeypatch.setenv("DISPLAY_TZ", "America/Denver")
    get_settings.cache_clear()
    init_db()
    started = datetime(2026, 9, 30, 2, 30, tzinfo=timezone.utc)
    with session_scope() as session:
        run = RunRow(
            status="completed",
            budget_usd=5.0,
            cost_usd=1.02,
            started_at=started,
            finished_at=datetime(2026, 9, 30, 2, 45, tzinfo=timezone.utc),
            warnings=[],
            source_health=[],
            stages=["archive"],
        )
        session.add(run)
        session.flush()
        session.add(
            DigestRow(
                run_id=run.id,
                date="2026-09-29",
                title="denver digest",
                markdown="# denver",
                top_ids=[],
                curated_count=0,
                killed_count=0,
                rejected_intersection_count=0,
                degraded=False,
                warnings=[],
            )
        )
    page = TestClient(app).get("/")
    assert page.status_code == 200
    assert "Sep 29, 8:30 PM MDT" in page.text
    assert "2026-09-29" in page.text
    get_settings.cache_clear()


def test_f8_cards_hide_unrecorded_sources_and_show_linked_ones():
    """Red against a card that links a URL the scout was not allowed to keep."""
    _clear("wo006-pre", "wo006-linked", "wo006-brief-secret", "wo006-brief-linked")
    secret = "https://secret.example/not-recorded"
    linked = "https://linked.example/brief"
    with session_scope() as session:
        run = RunRow(
            status="completed",
            budget_usd=5.0,
            started_at=datetime(2026, 9, 28, 16, 0, tzinfo=timezone.utc),
            warnings=[],
            source_health=[{"source": "hacker_news", "count": 10, "ok": True}],
            scout_seen={"hacker_news": 4},
            stages=["archive"],
        )
        session.add(run)
        session.flush()
        session.add(
            BriefRow(
                id="wo006-brief-secret",
                run_id=run.id,
                vertical="ai",
                headline="Secret headline that must not be linked",
                why_now="because",
                sources=[secret],
                raw_signals=["hacker_news"],
            )
        )
        session.add(
            BriefRow(
                id="wo006-brief-linked",
                run_id=run.id,
                vertical="health",
                headline="Linked headline from the brief",
                why_now="a named window",
                sources=[linked],
                raw_signals=["federal_register"],
            )
        )
        session.add(
            QuestionRow(
                id="wo006-pre",
                run_id=run.id,
                text="What staffing overflow follows if the unnamed pre-wo006 card is treated as sourced?",
                lens="contrarian",
                verticals=["ai"],
                coverage="thin",
                status="curated",
                rank=1,
                provenance="pre-wo006",
                written_by="",
                brief_ids=["wo006-brief-secret"],
            )
        )
        session.add(
            QuestionRow(
                id="wo006-linked",
                run_id=run.id,
                text="Who absorbs the overflow when the linked brief names the agency and the date?",
                lens="second_order",
                verticals=["health"],
                coverage="thin",
                status="curated",
                rank=2,
                provenance="linked",
                written_by="model:test-writer",
                brief_ids=["wo006-brief-linked"],
            )
        )
        session.add(
            DigestRow(
                run_id=run.id,
                date="2026-09-28",
                title="provenance cards",
                markdown="# cards",
                top_ids=["wo006-pre", "wo006-linked"],
                curated_count=2,
                killed_count=0,
                rejected_intersection_count=0,
                degraded=False,
                warnings=[],
            )
        )
    page = TestClient(app).get("/").text
    old = _article(page, "wo006-pre")
    assert "sources not recorded" in old
    assert secret not in old
    assert "<a " not in old
    fresh = _article(page, "wo006-linked")
    assert linked in fresh
    assert "Linked headline from the brief" in fresh
    assert "hacker_news: 10 fetched, 4 read" in page
    assert "What we read" in page


def test_f9_coverage_is_labelled_a_model_guess():
    """Red against a coverage word with no model-guess label on the card."""
    _clear("wo006-guess")
    with session_scope() as session:
        run = RunRow(status="completed", budget_usd=5.0, warnings=[], source_health=[], stages=["archive"])
        session.add(run)
        session.flush()
        session.add(
            QuestionRow(
                id="wo006-guess",
                run_id=run.id,
                text="Which office absorbs the overflow if the coverage word is only a model guess?",
                lens="opportunity",
                verticals=["business"],
                coverage="thin",
                status="curated",
                rank=1,
                provenance="unlinked",
                brief_ids=[],
            )
        )
        session.add(
            DigestRow(
                run_id=run.id,
                date="2026-09-27",
                title="guess",
                markdown="# guess",
                top_ids=["wo006-guess"],
                curated_count=1,
                killed_count=0,
                rejected_intersection_count=0,
                degraded=False,
                warnings=[],
            )
        )
    article = _article(TestClient(app).get("/").text, "wo006-guess")
    assert "coverage (model guess)" in article
    assert "sources not recorded" in article


def test_pre_wo006_backfill_rewrites_blank_provenance_only():
    """Red against leaving old questions unmarked, and against relabelling a new linked row."""
    _clear("wo006-blank-prov", "wo006-keep-linked")
    with session_scope() as session:
        run = RunRow(status="completed", budget_usd=5.0, warnings=[], source_health=[], stages=[])
        session.add(run)
        session.flush()
        session.add(
            QuestionRow(
                id="wo006-blank-prov",
                run_id=run.id,
                text="An old question whose provenance column was blank before the backfill.",
                lens="contrarian",
                verticals=["ai"],
                status="curated",
                provenance="linked",
            )
        )
        session.add(
            QuestionRow(
                id="wo006-keep-linked",
                run_id=run.id,
                text="A new question that already carries a real linked provenance value.",
                lens="contrarian",
                verticals=["ai"],
                status="curated",
                provenance="linked",
            )
        )
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("UPDATE questions SET provenance = '' WHERE id = 'wo006-blank-prov'"))
    from swarm.db import _migrate_wo006

    _migrate_wo006(engine)
    with session_scope() as session:
        blank = session.get(QuestionRow, "wo006-blank-prov")
        kept = session.get(QuestionRow, "wo006-keep-linked")
        assert blank is not None and blank.provenance == "pre-wo006"
        assert kept is not None and kept.provenance == "linked"


def _clear(*ids: str) -> None:
    init_db()
    with session_scope() as session:
        session.execute(delete(RatingRow).where(RatingRow.question_id.in_(ids)))
        session.execute(delete(QuestionRow).where(QuestionRow.id.in_(ids)))
        session.execute(delete(BriefRow).where(BriefRow.id.in_(ids)))


def _article(html: str, question_id: str) -> str:
    for block in re.findall(r"<article\b[\s\S]*?</article>", html):
        if f'data-id="{question_id}"' in block:
            return block
    pytest.fail(f"no article for {question_id}")
