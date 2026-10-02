"""WO-012: opportunity desk. Each test is red against the tree before the desk exists."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from dashboard.main import app
from swarm.budget import RunBudget
from swarm.db import init_db, session_scope
from swarm.desk.select import select_for_desk
from swarm.desk.validate import (
    apply_number_rule,
    filter_prospects,
    fit_from_assets,
    rivals_phrase,
)
from swarm.desk.verdicts import apply_verdict, verdict_history
from swarm.llm import LLM
from swarm.lock import release_lock
from swarm.orm import OpportunityRow, OpportunityVerdictRow, QuestionRow, RunRow
from swarm.agents.desk import CHECK_NOTE, run_desk, run_one_opportunity
from swarm.settings import get_settings


def _q(**kwargs):
    now = datetime(2026, 10, 2, 3, 0, tzinfo=timezone.utc)
    row = SimpleNamespace(
        id=kwargs.get("id", "q-1"),
        text=kwargs.get(
            "text",
            "If the earnings-test rule defunds STEM bachelor programs, who builds the first waiver list?",
        ),
        title=kwargs.get("title", "STEM programs at risk"),
        rank=kwargs.get("rank", 1),
        status=kwargs.get("status", "curated"),
        provenance=kwargs.get("provenance", "linked"),
        written_by=kwargs.get("written_by", "model:claude-sonnet-5"),
        promoted=kwargs.get("promoted", False),
        promoted_at=kwargs.get("promoted_at"),
        brief_ids=kwargs.get("brief_ids", ["b-1"]),
        created_at=now,
        run_id=kwargs.get("run_id", 24),
    )
    return row


def _brief(url="https://ed.gov/earnings-test", snippet=""):
    return SimpleNamespace(
        id="b-1",
        headline="Earnings-test rule",
        what_is_happening=snippet
        or (
            "The programs at risk are early-childhood certificates and counseling "
            "master's degrees, not STEM bachelor's degrees."
        ),
        why_now="Rule uses 2022-2023 wage data.",
        sources=[url],
        vertical="education",
    )


def _refusal_msg():
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text="I cannot continue.")],
        usage=SimpleNamespace(input_tokens=11, output_tokens=6),
        stop_reason="refusal",
    )


def _ok_msg(payload: dict):
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", name="emit", input=payload)],
        usage=SimpleNamespace(input_tokens=12, output_tokens=8),
        stop_reason="tool_use",
    )


class _Scripted:
    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("unexpected extra model call")
        return self.script.pop(0)


def _keyed(monkeypatch, script: list) -> tuple[LLM, _Scripted]:
    monkeypatch.setenv("FALLBACK_MODEL", "claude-opus-5-5")
    monkeypatch.setenv("JUDGMENT_MODEL", "claude-fable-5")
    monkeypatch.setenv("DESK_MODEL", "claude-fable-5")
    get_settings.cache_clear()
    client = _Scripted(script)
    llm = LLM(RunBudget(5.0))
    llm._client = SimpleNamespace(messages=client)
    return llm, client


def test_contradicted_premise_is_caught_and_card_continues():
    """Source says not-X; question assumes X → contradicted, card uses the correction."""
    evidence = (
        "The programs at risk are early-childhood certificates and counseling "
        "master's degrees, not STEM bachelor's degrees."
    )
    claims = [
        {
            "claim": "The earnings-test rule defunds STEM bachelor's degrees.",
            "verdict": "contradicted",
            "links": ["https://ed.gov/earnings-test"],
            "correction": (
                "The programs at risk are early-childhood certificates and "
                "counseling master's degrees."
            ),
        }
    ]
    card = {
        "whats_actually_true": (
            "The rule flags early-childhood certificates and counseling master's "
            "degrees, not STEM bachelor's degrees."
        ),
        "who_has_problem": "early-childhood certificate programs",
        "who_pays": "state aid offices",
        "what_they_use_today": "unknown",
        "why_now": "2022-2023 wage data",
        "how_it_charges": "subscription",
        "rivals": [],
        "first_prospects": [],
        "weekend_test": "Call two certificate programs named in the rule.",
        "why_it_might_fail": "The Department may waive those programs.",
        "red_flags": ["regulated field"],
        "shapes": [
            {"kind": "service", "line": "Audit which programs are actually flagged.", "picked": True},
            {"kind": "software", "line": "A checker against the Department file.", "picked": False},
            {"kind": "data product", "line": "A flagged-program list.", "picked": False},
        ],
    }
    out = run_one_opportunity(
        question=_q(),
        briefs=[_brief(snippet=evidence)],
        claims=claims,
        card=card,
        searches=[],
        assets={},
        n_searches=2,
    )
    assert out["claims"][0]["verdict"] == "contradicted"
    assert "early-childhood" in out["whats_actually_true"]
    assert "STEM bachelor" not in out["who_has_problem"]
    assert CHECK_NOTE in out["check_note"]


def test_unsourced_number_is_rejected_then_not_available():
    """A number absent from every snippet is stripped; a second miss becomes not available."""
    evidence = "About 1,200 programs were flagged in the Department's data."
    first = {"who_has_problem": "12,000 programs need a new waiver desk"}
    cleaned, dirty = apply_number_rule(first, evidence)
    assert dirty is True
    assert "12,000" not in cleaned["who_has_problem"]
    second = {"who_has_problem": "12,000 programs still"}
    cleaned2, dirty2 = apply_number_rule(second, evidence, second_pass=True)
    assert dirty2 is True
    assert cleaned2["who_has_problem"] == "not available"


def test_number_rule_does_not_leave_a_blank_field():
    """Stripping every number from a short field must not wipe What's actually true."""
    cleaned, dirty = apply_number_rule(
        {"whats_actually_true": "2026"},
        evidence="no digits in the snippets",
    )
    assert dirty is True
    assert cleaned["whats_actually_true"] == "not available"


def test_no_rivals_is_phrased_as_a_search():
    line = rivals_phrase([], n_searches=2)
    assert line == "none found in 2 searches"
    assert "no competitors" not in line.lower()


def test_prospects_must_appear_in_fetched_text():
    evidence = "Stanford and Purdue filed comments on the earnings-test docket."
    kept = filter_prospects(["Stanford", "Acme Corp", "Purdue"], evidence)
    assert kept == ["Stanford", "Purdue"]


def test_empty_assets_profile_is_named():
    assert fit_from_assets({}) == "assets profile not written"
    assert fit_from_assets({"businesses": "  ", "reach": ""}) == "assets profile not written"
    assert "not written" not in fit_from_assets({"businesses": "A roofing firm in Denver"})


def test_selection_skips_unlinked_includes_saved_and_holds_the_cap(monkeypatch):
    monkeypatch.setenv("OPPORTUNITY_MAX", "2")
    get_settings.cache_clear()
    prev = datetime(2026, 10, 2, 2, 28, tzinfo=timezone.utc)
    saved = _q(
        id="saved-1",
        rank=40,
        promoted=True,
        promoted_at=datetime(2026, 10, 2, 2, 40, tzinfo=timezone.utc),
        title="Saved since last run",
    )
    unlinked = _q(id="u-1", rank=1, provenance="unlinked")
    unverified = _q(id="v-1", rank=2, provenance="unverified")
    top = _q(id="t-1", rank=1, provenance="linked")
    extra = _q(id="t-2", rank=2, provenance="linked")
    picks, skipped = select_for_desk(
        [unlinked, unverified, top, extra, saved],
        previous_started=prev,
        max_n=2,
    )
    ids = [p.id for p in picks]
    assert "u-1" not in ids and "v-1" not in ids
    assert any(s.id == "u-1" and "unlinked" in s.skip_reason for s in skipped)
    assert "saved-1" in ids
    assert len(picks) == 2


def test_pursue_and_kill_need_a_why_and_redecide_keeps_history():
    init_db()
    with session_scope() as session:
        session.query(OpportunityVerdictRow).delete()
        session.query(OpportunityRow).filter(OpportunityRow.id == "opp-hist").delete()
        if session.get(RunRow, 900) is None:
            session.add(RunRow(id=900, status="completed"))
            session.flush()
        session.add(
            OpportunityRow(
                id="opp-hist",
                run_id=900,
                question_id="q-hist",
                status="completed",
            )
        )
    try:
        apply_verdict("opp-hist", "pursue", "")
        raise AssertionError("pursue without why should fail")
    except ValueError:
        pass
    apply_verdict("opp-hist", "park", "")
    apply_verdict("opp-hist", "kill", "No way to reach the buyer")
    hist = verdict_history("opp-hist")
    assert [h["verdict"] for h in hist] == ["park", "kill"]
    assert hist[1]["why"] == "No way to reach the buyer"


def test_over_budget_skips_the_desk_and_names_it():
    llm = LLM(RunBudget(0.50))
    llm.budget.spent_usd = 0.49
    warnings: list[str] = []
    cards = run_desk(
        run_id=24,
        questions=[_q()],
        briefs=[_brief()],
        llm=llm,
        search_fn=lambda _q: [],
        assets={},
        previous_started=None,
        warnings=warnings,
    )
    assert cards == []
    assert any("Opportunity desk skipped" in w and "budget" in w for w in warnings)


def test_desk_refusal_uses_wo010_fallback(monkeypatch):
    claims = {
        "claims": [
            {
                "claim": "Treasury now runs student-loan default collection.",
                "why_it_matters": "The collector changed.",
            }
        ]
    }
    llm, client = _keyed(monkeypatch, [_refusal_msg(), _ok_msg(claims)])
    llm.agent = "desk"
    from swarm.agents.desk import name_claims

    out = name_claims(
        question=_q(text="Now that student-loan default collection runs through Treasury, who sells the offset tooling?"),
        briefs=[_brief()],
        llm=llm,
    )
    assert out and out[0]["claim"].startswith("Treasury")
    assert client.calls[0]["model"] == "claude-fable-5"
    assert client.calls[1]["model"] == "claude-opus-5-5"
    assert client.calls[0]["messages"] == client.calls[1]["messages"]
    assert llm.refusal_recoveries == ["claude-opus-5-5"]


def test_assay_this_stops_at_daily_ceiling(monkeypatch):
    monkeypatch.setenv("ASSAYS_PER_DAY", "1")
    get_settings.cache_clear()
    init_db()
    with session_scope() as session:
        session.query(OpportunityVerdictRow).delete()
        session.query(OpportunityRow).delete()
        if session.get(RunRow, 901) is None:
            session.add(RunRow(id=901, status="completed"))
            session.flush()
        if session.get(QuestionRow, "q-assay-ceil") is None:
            session.add(
                QuestionRow(
                    id="q-assay-ceil",
                    run_id=901,
                    text="If verification of an AI-math claim needs the same cluster, who builds the independent layer?",
                    title="Independent verification",
                    lens="opportunity",
                    provenance="linked",
                    written_by="model:claude-sonnet-5",
                    status="curated",
                    rank=1,
                )
            )
        session.add(
            OpportunityRow(
                id="opp-already",
                run_id=901,
                question_id="other",
                status="completed",
                on_demand=True,
            )
        )
    client = TestClient(app)
    res = client.post("/api/questions/q-assay-ceil/assay")
    assert res.status_code == 429
    assert "ASSAYS_PER_DAY" in res.text


def test_status_ignores_a_running_row_without_the_lock():
    """Run 24 was killed mid-scout. The banner must not stay on forever."""
    init_db()
    release_lock()
    with session_scope() as session:
        session.query(RunRow).filter(RunRow.id == 925).delete()
        session.add(RunRow(id=925, status="running", current_stage="scout"))
    client = TestClient(app)
    res = client.get("/api/status")
    assert res.status_code == 200
    assert res.json()["running"] is False
    page = client.get("/")
    assert "Swarm is running" not in page.text
    with session_scope() as session:
        leftover = session.get(RunRow, 925)
        if leftover is not None:
            leftover.status = "failed"
            leftover.error = "test cleanup"
            leftover.finished_at = datetime.now(timezone.utc)
