"""WO-011: per-scout links, single-field reject, FR filter, movers, new verticals.

Assertions that go red against the unfixed e11bd3b code are marked RED TODAY.
"""

from swarm.agents.cross_pollinator import run_cross_pollinator
from swarm.agents.scout import _llm_briefs, signals_for_vertical, urls_from_model
from swarm.budget import RunBudget
from swarm.config import verticals
from swarm.llm import LLM
from swarm.models import Brief, Intersection, Question, QuestionStatus, Signal
from swarm.primary import prefer_primary_urls
from swarm.sources.federal_register import is_housekeeping, keep_document
from swarm.sources.gdelt import articles_to_signals
from swarm.sources.movers import describe_move, emit_movers
from dashboard.honesty import from_cites, sources_linked_line


def _signal(source: str, title: str, url: str, hints: list[str] | None = None) -> Signal:
    return Signal(
        source=source,
        title=title,
        url=url,
        snippet=title,
        score=2.0,
        vertical_hints=hints or [],
    )


def test_labels_resolve_per_scout():
    """S1 is that scout's first signal. Green today; hypothesis did not hold."""
    health = _signal("brave", "FDA mRNA flu", "https://health.example/s1", ["health"])
    ai = _signal("brave", "Cloudflare Clef", "https://ai.example/s1", ["ai"])
    health_labels = {"S1": health}
    ai_labels = {"S1": ai}
    health_urls = urls_from_model({"signal_refs": ["S1"]}, health_labels)
    ai_urls = urls_from_model({"signal_refs": ["S1"]}, ai_labels)
    assert health_urls == ["https://health.example/s1"]
    assert ai_urls == ["https://ai.example/s1"]
    assert health_urls != ai_urls


def test_foreign_refs_dropped_and_brief_unlinked():
    """RED TODAY: prefer_primary_urls / from_cites padded uncited primaries."""
    own = _signal("brave", "Teacher shortage", "https://edu.example/own", ["education"])
    foreign = _signal(
        "federal_register",
        "Airworthiness Directives; Airbus SAS Airplanes",
        "https://www.federalregister.gov/airbus",
        [],
    )
    llm = LLM(RunBudget(5.0))
    llm._client = object()

    def _payload(**_k):
        return {
            "briefs": [
                {
                    "headline": "Teacher-prep earnings rule",
                    "what_is_happening": "A federal rule on program accountability.",
                    "why_now": "published",
                    "who_is_affected": "schools",
                    "velocity": "steady",
                    "signal_refs": ["S99"],
                    "source_urls": [foreign.url],
                }
            ]
        }

    llm.complete_json = _payload  # type: ignore[method-assign]
    out = _llm_briefs(
        {"id": "education", "name": "Education"},
        [(own, 1)],
        llm,
        22,
    )
    assert out
    assert out[0].sources == []

    padded = prefer_primary_urls(
        "A federal rule on program accountability",
        [],
        [own, foreign],
    )
    assert padded == []

    question = Question(
        id="q-unlinked",
        text="Who absorbs the students if the rule strands teacher-prep?",
        lens="contrarian",
        verticals=["education"],
        brief_ids=[out[0].id],
        provenance="linked",
        status=QuestionStatus.curated,
    )
    cites = from_cites(question, {out[0].id: out[0]}, {foreign.url: foreign})
    assert cites["cites"] == []


def test_sources_linked_count_is_honest():
    """RED TODAY: counted provenance on curated only, not checked refs."""
    linked = Brief(
        id="b-ok",
        vertical="health",
        headline="mFlusiva",
        what_is_happening="FDA approval",
        why_now="now",
        who_is_affected="patients",
        sources=["https://pharmacytimes.com/mflusiva"],
    )
    empty = Brief(
        id="b-empty",
        vertical="ai",
        headline="chips",
        what_is_happening="a rule-shaped brief",
        why_now="now",
        who_is_affected="fabs",
        sources=[],
    )
    questions = [
        Question(
            id="q1",
            text="If mFlusiva's confirmatory trial slips, who inherits the 65+ cohort?",
            lens="contrarian",
            status=QuestionStatus.curated,
            brief_ids=["b-ok"],
            provenance="linked",
        ),
        Question(
            id="q2",
            text="Which EDA desk runs a second non-AI pass on model-generated netlists?",
            lens="contrarian",
            status=QuestionStatus.killed,
            brief_ids=["b-empty"],
            provenance="linked",
        ),
        Question(
            id="q3",
            text="Who sells detection for agents fine-tuned on a public exploit benchmark?",
            lens="contrarian",
            status=QuestionStatus.curated,
            brief_ids=["b-empty"],
            provenance="linked",
        ),
    ]
    line, _warn = sources_linked_line(questions, {linked.id: linked, empty.id: empty})
    assert line == "Sources linked: 1 of 3"


def test_same_field_pairing_rejected():
    """RED TODAY: ai × ai is accepted."""
    briefs = [
        Brief(
            id="a",
            vertical="ai",
            headline="Clef",
            what_is_happening="open weights",
            why_now="now",
            who_is_affected="labs",
        ),
        Brief(
            id="b",
            vertical="ai",
            headline="KaliBench",
            what_is_happening="commands",
            why_now="now",
            who_is_affected="vendors",
        ),
    ]
    llm = LLM(RunBudget(5.0))
    llm._client = object()

    def _payload(**_k):
        return {
            "intersections": [
                {
                    "verticals": ["ai", "ai"],
                    "thesis": "Open weights plus a public exploit benchmark.",
                    "surprise": 0.6,
                    "plausibility": 0.7,
                    "coverage": "thin",
                    "accepted": True,
                    "reject_reason": "",
                    "brief_headlines": ["Clef", "KaliBench"],
                }
            ]
        }

    llm.complete_json = _payload  # type: ignore[method-assign]
    out = run_cross_pollinator(briefs, llm, run_id=22)
    assert out
    assert out[0].accepted is False
    assert out[0].reject_reason == "single field"
    assert any("single field" in line for line in getattr(run_cross_pollinator, "passed_over", []))


def test_federal_register_drops_ad_and_renewal():
    """RED TODAY: both became signals on run 22."""
    ad = {
        "title": "Airworthiness Directives; Airbus SAS Airplanes",
        "type": "Rule",
        "html_url": "https://www.federalregister.gov/airbus",
    }
    renewal = {
        "title": "Advisory Committee; Antimicrobial Drugs Advisory Committee; Renewal",
        "type": "Notice",
        "html_url": "https://www.federalregister.gov/renewal",
    }
    rule = {
        "title": "Medicare coverage of anti-obesity medication",
        "type": "Rule",
        "html_url": "https://www.federalregister.gov/medicare-obesity",
    }
    assert is_housekeeping(ad["title"])
    assert is_housekeeping(renewal["title"])
    assert keep_document(ad) is False
    assert keep_document(renewal) is False
    assert keep_document(rule) is True


def test_movers_write_the_computed_number_or_nothing():
    values = [10.0, 10.2, 10.1, 10.3, 10.0, 10.1, 10.2, 10.0, 9.9, 10.1, 10.0, 10.2, 10.1, 4.0]
    dates = [f"2026-09-{i:02d}" for i in range(1, 15)]
    move = describe_move(values, dates, label="US crude inventories", unit="M barrels")
    assert move is not None
    text, data_date, raw = move
    assert "US crude inventories" in text
    assert "-6.1 M barrels" in text or "−6.1" in text or "-6.1" in text
    assert data_date == "2026-09-14"
    assert raw["data_date"] == "2026-09-14"
    signals = emit_movers(
        source="eia",
        series_id="PET.WCRSTUS1.W",
        label="US crude inventories",
        unit="M barrels",
        values=values,
        dates=dates,
        url="https://www.eia.gov/crude",
        vertical="commodities",
    )
    assert signals
    assert "2026-09-14" in signals[0].snippet
    assert signals[0].raw["change"] == raw["change"]

    quiet = [10.0 + (i % 3) * 0.05 for i in range(16)]
    quiet_dates = [f"2026-08-{i:02d}" for i in range(1, 17)]
    assert describe_move(quiet, quiet_dates, label="US crude inventories", unit="M barrels") is None


def test_gdelt_item_reaches_geopolitics_scout():
    verticals.cache_clear()
    ids = {v["id"] for v in verticals()}
    assert "geopolitics" in ids
    assert "commodities" in ids
    articles = [
        {
            "title": "OFAC tightens Russian oil sanctions after a tanker seizure",
            "url": "https://gdelt.example/ofac-sanctions",
            "seendate": "20261002T010000Z",
            "domain": "reuters.com",
        }
    ]
    signals = articles_to_signals(articles, vertical_id="geopolitics", query="sanctions")
    assert signals[0].vertical_hints == ["geopolitics"]
    taken = signals_for_vertical("geopolitics", signals)
    assert any(sig.url == "https://gdelt.example/ofac-sanctions" for sig, _rank in taken)


def test_link_repair_runs_once_and_records_the_marker():
    from swarm.db import init_db, session_scope
    from swarm.orm import BriefRow, DeployMarkerRow
    from swarm.repair_links import MARKER, repair_already_ran, repair_past_links

    init_db()
    with session_scope() as session:
        existing = session.get(DeployMarkerRow, MARKER)
        if existing is not None:
            session.delete(existing)

    first = repair_past_links()
    assert first["skipped"] == 0
    assert repair_already_ran() is True

    with session_scope() as session:
        planted = session.query(BriefRow).first()
        if planted is not None:
            planted.sources = ["https://example.com/should-not-survive-a-second-repair"]
            planted_id = planted.id
        else:
            planted_id = None

    second = repair_past_links()
    assert second["skipped"] == 1
    if planted_id:
        with session_scope() as session:
            row = session.get(BriefRow, planted_id)
            assert row is not None
            assert row.sources == ["https://example.com/should-not-survive-a-second-repair"]
