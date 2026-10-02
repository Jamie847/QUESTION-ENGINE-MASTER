"""U3: From: is the signal behind the URL. Primary records first.

Red against the unfixed code: from_line prints the scout headline and
raw_signals names (wikipedia) next to commentary URLs.
"""

from fastapi.testclient import TestClient

from dashboard.honesty import from_cites, from_line
from dashboard.main import app
from swarm.agents.scout import _llm_briefs
from swarm.budget import RunBudget
from swarm.db import init_db, session_scope
from swarm.llm import LLM
from swarm.models import Brief, Question, Signal
from swarm.orm import BriefRow, DigestRow, QuestionRow, RunRow, SignalRow
from swarm.primary import prefer_primary_urls


FR_URL = "https://www.federalregister.gov/documents/2026/01/15/ed-gainful"
NEWS_URL = "https://thesource.com/trump-gainful-employment"
TOWN_URL = "https://townhall.com/gainful-take"
IBT_URL = "https://www.ibtimes.co.uk/gainful-stem"


def _rank3_shape():
    """Run 20 rank 3: wikipedia-flavoured brief, commentary URLs."""
    fr = Signal(
        source="federal_register",
        title="Financial Value Transparency and Gainful Employment",
        url=FR_URL,
        snippet="Department of Education final earnings-accountability rule.",
        vertical_hints=["education"],
        score=1.1,
    )
    news = Signal(
        source="brave",
        title="Trump's new gainful employment rule hits STEM",
        url=NEWS_URL,
        snippet="commentary",
        score=4.0,
    )
    town = Signal(
        source="brave",
        title="Townhall on gainful employment",
        url=TOWN_URL,
        snippet="commentary",
        score=3.0,
    )
    ibt = Signal(
        source="brave",
        title="IBTimes on teaching programs",
        url=IBT_URL,
        snippet="commentary",
        score=2.0,
    )
    brief = Brief(
        id="r20-education-trump-s-new-gainful-empl-64819abf5d",
        vertical="education",
        headline="Trump's new gainful-employment rule (wikipedia)",
        what_is_happening="A federal rule on earnings accountability.",
        why_now="now",
        who_is_affected="teaching programs",
        sources=[NEWS_URL, TOWN_URL, IBT_URL],
        raw_signals=["wikipedia", "brave", "arxiv", "wikipedia"],
    )
    question = Question(
        id="q-rank3",
        text="If the gainful-employment rule strands STEM bachelor's programs, who absorbs the students?",
        lens="contrarian",
        verticals=["education"],
        brief_ids=[brief.id],
        provenance="linked",
    )
    return question, brief, [fr, news, town, ibt]


def test_from_line_uses_signal_title_and_domain_not_headline_alone():
    question, brief, signals = _rank3_shape()
    briefs = {brief.id: brief}
    by_url = {s.url: s for s in signals}
    line = from_line(question, briefs, by_url)
    cites = from_cites(question, briefs, by_url)
    assert "thesource.com" in line
    by_domain = {c["domain"]: c for c in cites["cites"]}
    assert "thesource.com" in by_domain
    assert by_domain["thesource.com"]["title"] == "Trump's new gainful employment rule hits STEM"
    assert by_domain["thesource.com"]["source"] == "brave"
    assert all(c["source"] != "wikipedia" for c in cites["cites"])
    # Headline may appear as the summary, not as the source label.
    assert cites["summary"].startswith("Trump's new gainful-employment")


def test_every_label_matches_the_signal_behind_its_url():
    question, brief, signals = _rank3_shape()
    by_url = {s.url: s for s in signals}
    cites = from_cites(question, {brief.id: brief}, by_url)
    for cite in cites["cites"]:
        sig = by_url[cite["url"]]
        assert cite["source"] == sig.source
        assert cite["title"] == sig.title
        assert cite["domain"] in cite["url"]


def test_primary_record_is_cited_first_for_a_rule():
    question, brief, signals = _rank3_shape()
    ordered = prefer_primary_urls(
        "Department of Education final earnings-accountability rule",
        [NEWS_URL],
        signals,
    )
    assert ordered == [NEWS_URL]

    cited = prefer_primary_urls(
        "Department of Education final earnings-accountability rule",
        [NEWS_URL, FR_URL],
        signals,
    )
    assert cited[0] == FR_URL
    assert NEWS_URL in cited

    cites = from_cites(
        question,
        {brief.id: brief},
        {s.url: s for s in signals},
    )
    assert [c["url"] for c in cites["cites"]] == [NEWS_URL, TOWN_URL, IBT_URL]


def test_card_from_uses_signal_not_wikipedia_label():
    init_db()
    question, brief, signals = _rank3_shape()
    with session_scope() as session:
        session.query(DigestRow).delete()
        run = RunRow(status="completed", budget_usd=5)
        session.add(run)
        session.flush()
        rid = run.id
        brief_id = f"{brief.id}-{rid}"
        session.add(
            BriefRow(
                id=brief_id,
                run_id=rid,
                vertical="ai",
                headline=brief.headline,
                what_is_happening=brief.what_is_happening,
                sources=brief.sources,
                raw_signals=brief.raw_signals,
            )
        )
        session.add(
            DigestRow(
                run_id=rid,
                date="2026-09-30",
                title="rank3",
                markdown="# r",
                top_ids=[f"q-rank3-{rid}"],
                curated_count=1,
            )
        )
        session.add(
            QuestionRow(
                id=f"q-rank3-{rid}",
                run_id=rid,
                text=question.text,
                lens="contrarian",
                verticals=["ai"],
                status="curated",
                rank=3,
                brief_ids=[brief_id],
                provenance="linked",
            )
        )
        for sig in signals:
            session.add(
                SignalRow(
                    run_id=rid,
                    source=sig.source,
                    title=sig.title,
                    url=sig.url,
                    snippet=sig.snippet,
                    score=sig.score,
                )
            )
    page = TestClient(app).get("/")
    assert page.status_code == 200
    assert "thesource.com" in page.text
    assert "Financial Value Transparency and Gainful Employment" not in page.text
    assert "federalregister.gov" not in page.text.split("From:")[1][:400]
    # The wikipedia scout-mix name is not the From: label.
    assert "(wikipedia)" not in page.text.split("From:")[1][:200]


def test_scout_llm_brief_cites_federal_register_for_a_rule():
    signals = [
        Signal(
            source="federal_register",
            title="Financial Value Transparency and Gainful Employment",
            url=FR_URL,
            snippet="final rule",
            score=1.1,
        ),
        Signal(
            source="brave",
            title="Op-ed on the rule",
            url=NEWS_URL,
            snippet="commentary",
            score=5.0,
        ),
    ]
    llm = LLM(RunBudget(5.0))
    llm._client = object()

    def _payload(**_k):
        return {
            "briefs": [
                {
                    "headline": "Education's gainful-employment rule",
                    "what_is_happening": "A final earnings-accountability rule.",
                    "why_now": "published",
                    "who_is_affected": "teaching programs",
                    "velocity": "accelerating",
                    "source_urls": [NEWS_URL],
                }
            ]
        }

    llm.complete_json = _payload  # type: ignore[method-assign]
    cfg = {"id": "ai", "name": "AI"}
    out = _llm_briefs(cfg, [(s, i + 1) for i, s in enumerate(signals)], llm, 20)
    assert out
    assert out[0].sources == [NEWS_URL]
