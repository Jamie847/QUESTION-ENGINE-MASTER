"""WO-010: refusal retry, no keyed templates, source-link count, plain failures.

Each test names the assertion that went red against the unfixed code.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

from dashboard.honesty import failure_lines_from_warnings, sources_linked_line
from dashboard.main import app
from swarm.agents.cross_pollinator import run_cross_pollinator
from swarm.agents.curator import CuratorFallback, run_curator
from swarm.agents.scout import run_scouts
from swarm.agents.smiths import SCHEMA as SMITH_SCHEMA
from swarm.agents.smiths import run_smiths
from swarm.budget import RunBudget
from swarm.db import init_db, session_scope
from swarm.llm import LLM
from swarm.models import Brief, Coverage, Question, Signal, TasteProfile, Velocity
from swarm.orm import (
    AgentCallRow,
    BriefRow,
    DigestRow,
    IntersectionRow,
    KillReasonRow,
    QuestionRow,
    RatingRow,
    RunRow,
    SignalRow,
)
from swarm.run_daily import main as swarm_main
from swarm.settings import get_settings
from swarm.taste import load_seed_profile


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
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    get_settings.cache_clear()
    client = _Scripted(script)
    llm = LLM(RunBudget(5.0))
    llm._client = SimpleNamespace(messages=client)
    return llm, client


def _briefs(n: int = 2) -> list[Brief]:
    return [
        Brief(
            id=f"b-{i}",
            vertical=("ai", "health", "business")[(i - 1) % 3],
            headline=f"Headline {i} about compute and clinics",
            what_is_happening="happening",
            why_now="now",
            who_is_affected="operators",
            velocity=Velocity.steady,
            sources=[f"https://example.com/{i}"],
        )
        for i in range(1, n + 1)
    ]


def _seed_today(*, warnings: list[str], questions: list[dict], git_commit: str = "") -> int:
    init_db()
    with session_scope() as session:
        session.query(RatingRow).delete()
        session.query(QuestionRow).delete()
        session.query(DigestRow).delete()
        session.query(AgentCallRow).delete()
        session.query(IntersectionRow).delete()
        session.query(BriefRow).delete()
        session.query(SignalRow).delete()
        session.query(KillReasonRow).delete()
        session.query(RunRow).delete()
        run = RunRow(
            status="completed",
            budget_usd=5,
            warnings=list(warnings),
            git_commit=git_commit,
            started_at=datetime.now(timezone.utc),
        )
        session.add(run)
        session.flush()
        rid = run.id
        ids = []
        seeded_briefs: set[str] = set()
        for i, q in enumerate(questions, start=1):
            qid = q.get("id") or f"wo010-{rid}-{i}"
            ids.append(qid)
            for bid in q.get("brief_ids", ["b-1"]):
                if not bid or bid in seeded_briefs:
                    continue
                seeded_briefs.add(bid)
                session.add(
                    BriefRow(
                        id=bid,
                        run_id=rid,
                        vertical="health",
                        headline=bid,
                        sources=[f"https://example.com/{bid}"],
                    )
                )
            session.add(
                QuestionRow(
                    id=qid,
                    run_id=rid,
                    text=q.get(
                        "text",
                        "If cash-pay GLP-1 users quit at month 18, which clinics still price forever?",
                    ),
                    title=q.get("title", "Clinics priced for forever"),
                    lens=q.get("lens", "contrarian"),
                    verticals=q.get("verticals", ["health"]),
                    status="curated",
                    rank=i,
                    provenance=q.get("provenance", "linked"),
                    written_by=q.get("written_by", "model:claude-sonnet-5"),
                    brief_ids=q.get("brief_ids", ["b-1"]),
                )
            )
        session.add(
            DigestRow(
                run_id=rid,
                date="2099-10-01",
                title="wo010 today",
                markdown="# wo010",
                top_ids=ids[:5],
                curated_count=len(ids),
                warnings=list(warnings),
            )
        )
    return rid


def test_wo010_refusal_recovers(monkeypatch):
    """Red today: the stage falls back to templates / returns None after one row."""
    init_db()
    with session_scope() as session:
        run = RunRow(status="running", budget_usd=5)
        session.add(run)
        session.flush()
        run_id = run.id

    payload = {"ok": True, "intersections": []}
    llm, client = _keyed(monkeypatch, [_refusal_msg(), _ok_msg(payload)])
    llm.run_id = run_id
    llm.agent = "cross_pollinator"
    data = llm.complete_json(
        system="pair topics",
        user="Today's briefs:\n- CRISPR biolab",
        schema={"type": "object"},
        judgment=True,
    )
    assert data == payload
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(AgentCallRow)
                .where(AgentCallRow.run_id == run_id)
                .order_by(AgentCallRow.id)
            )
        )
    assert len(rows) == 2
    assert rows[0].ok is False
    assert rows[0].model == "claude-fable-5"
    assert "refusal" in rows[0].error
    assert rows[1].ok is True
    assert rows[1].model == "claude-opus-5-5"
    assert rows[1].retry_of == rows[0].id
    assert any(
        "Topic pairing: refused by claude-fable-5, recovered on claude-opus-5-5." == line
        for line in llm.failure_lines
    )


def test_wo010_prompt_unchanged_on_retry(monkeypatch):
    """Red today: there is no second call, or the prompt is trimmed to dodge the refusal."""
    llm, client = _keyed(monkeypatch, [_refusal_msg(), _ok_msg({"ok": True})])
    llm.agent = "cross_pollinator"
    system = "pair topics — do not rewrite this"
    user = "Today's briefs:\n- Anthropic's AI biolab claims a CRISPR-comparable discovery"
    assert llm.complete_json(system=system, user=user, schema={"type": "object"}, judgment=True)
    assert len(client.calls) == 2
    first, second = client.calls
    assert first["model"] == "claude-fable-5"
    assert second["model"] == "claude-opus-5-5"
    assert first["system"] == second["system"] == system
    assert first["messages"] == second["messages"]
    assert first["messages"][0]["content"] == user
    assert first["tools"] == second["tools"]


def test_wo010_double_refusal_skips_pairings(monkeypatch):
    """Red today: template intersections appear (share a compute stake…)."""
    llm, _client = _keyed(monkeypatch, [_refusal_msg(), _refusal_msg()])
    llm.agent = "cross_pollinator"
    inters = run_cross_pollinator(_briefs(4), llm, run_id=21)
    assert inters == []
    assert not any("share a" in (i.thesis or "") and "stake" in (i.thesis or "") for i in inters)

    captured: dict[str, str] = {}

    def _smith(**kwargs):
        captured["user"] = kwargs["user"]
        return {
            "questions": [
                {
                    "text": "If the cash-pay GLP-1 cohort leaves at month 18, which clinics still price as if they stay?",
                    "verticals": ["health"],
                    "coverage": "thin",
                    "decay_class": "slow",
                    "context": "adherence",
                    "intersection_ref": "none",
                    "brief_refs": ["B1"],
                }
            ]
        }

    smith = LLM(RunBudget(5.0))
    smith._client = object()
    smith.complete_json = _smith  # type: ignore[method-assign]
    questions, _reports = run_smiths(_briefs(3), inters, TasteProfile(), smith, run_id=21)
    assert questions
    assert all(q.written_by.startswith("model:") for q in questions)
    assert "No pairings are available this run" in captured["user"]

    warning = "No topic pairings this run. Topic pairing: refused by claude-fable-5."
    _seed_today(warnings=[warning], questions=[{"provenance": "linked"}])
    page = TestClient(app).get("/")
    assert page.status_code == 200
    assert "No topic pairings this run" in page.text
    assert "share a compute stake" not in page.text


def test_wo010_curator_double_refusal_writes_no_digest(monkeypatch):
    """Red today: a heuristic digest archives after the judgment model refuses."""
    init_db()
    monkeypatch.setenv("FALLBACK_MODEL", "claude-opus-5-5")
    get_settings.cache_clear()
    with session_scope() as session:
        run = RunRow(
            status="running",
            budget_usd=5,
            stages=["fetch", "scout", "cross_pollinate", "smith", "dedup"],
            warnings=[],
            source_health=[],
        )
        session.add(run)
        session.flush()
        run_id = run.id
        session.add(
            QuestionRow(
                id=f"wo010-cur-{run_id}",
                run_id=run_id,
                text="If GLP-1 adherence collapses after 18 months for the cash-pay cohort, which clinics are priced as if patients stay?",
                lens="second_order",
                verticals=["health"],
                status="raw",
            )
        )

    class RefusingJudgment(LLM):
        def __init__(self, budget):
            super().__init__(budget)
            self._client = SimpleNamespace(
                messages=_Scripted([_refusal_msg(), _refusal_msg()])
            )

    from swarm import run_daily

    orig = run_daily.LLM
    run_daily.LLM = RefusingJudgment
    try:
        assert swarm_main(["--resume", str(run_id), "--force"]) == 1
    finally:
        run_daily.LLM = orig
        get_settings.cache_clear()

    with session_scope() as session:
        row = session.get(RunRow, run_id)
        digest = session.scalar(select(DigestRow).where(DigestRow.run_id == run_id))
        assert row is not None
        assert row.status == "failed"
        assert digest is None

    llm, _ = _keyed(monkeypatch, [_refusal_msg(), _refusal_msg()])
    try:
        run_curator(
            [
                Question(
                    id="good",
                    text="If GLP-1 adherence collapses after 18 months for the cash-pay cohort, which clinics are priced as if patients stay?",
                    lens="second_order",
                    verticals=["health"],
                )
            ],
            load_seed_profile(),
            llm,
        )
        raise AssertionError("old code would have archived a heuristic ranking")
    except CuratorFallback:
        pass


def test_wo010_questions_cite_briefs_with_no_intersections(monkeypatch):
    """Red today: briefs[:16] so B20 is unlinked; header has no Sources linked line."""
    assert SMITH_SCHEMA["properties"]["questions"]["items"]["properties"]["brief_refs"][
        "minItems"
    ] == 1

    captured: dict[str, str] = {}
    briefs = _briefs(20)

    def _payload(**kwargs):
        captured["user"] = kwargs["user"]
        return {
            "questions": [
                {
                    "text": "Who staffs the overflow if headline 1 and headline 20 stay on the same calendar?",
                    "verticals": ["ai"],
                    "coverage": "thin",
                    "decay_class": "slow",
                    "context": "staffing",
                    "intersection_ref": "none",
                    "brief_refs": ["B1", "B20"],
                },
                {
                    "text": "What document would prove the reverse of headline 17?",
                    "verticals": ["health"],
                    "coverage": "unknown",
                    "decay_class": "slow",
                    "context": "proof",
                    "intersection_ref": "none",
                    "brief_refs": ["B99"],
                },
            ]
        }

    llm = LLM(RunBudget(5.0))
    llm._client = object()
    llm.complete_json = _payload  # type: ignore[method-assign]
    out, _reports = run_smiths(briefs, [], TasteProfile(), llm, run_id=37)
    assert "B20" in captured["user"]
    assert "B17" in captured["user"]
    assert "No pairings are available this run" in captured["user"]
    linked = [q for q in out if q.provenance == "linked"]
    unlinked = [q for q in out if q.provenance == "unlinked"]
    assert linked
    assert all(q.brief_ids for q in linked)
    assert "b-1" in linked[0].brief_ids
    assert "b-20" in linked[0].brief_ids
    assert unlinked
    assert all(not q.brief_ids for q in unlinked)

    line, warn = sources_linked_line(out)
    assert line.startswith("Sources linked:")
    assert " of " in line

    _seed_today(
        warnings=[],
        questions=[
            {"provenance": "linked", "brief_ids": ["b-1"]},
            {"provenance": "unlinked", "brief_ids": []},
            {"provenance": "linked", "brief_ids": ["b-2"]},
        ],
    )
    page = TestClient(app).get("/")
    assert "Sources linked: 2 of 3" in page.text
    assert "Sources linked below 80%" in page.text


def test_wo010_plain_failure_line():
    """Red today: Today says A model call failed. See service logs."""
    line = "Topic pairing: refused by claude-fable-5, recovered on claude-opus-5-5."
    shown = failure_lines_from_warnings(
        [
            line,
            "Anthropic: credit balance too low (req_SECRET99)",
            "Last error: BadRequestError status=400 | req_abc",
        ]
    )
    assert line in shown
    assert all("req_" not in item for item in shown)
    assert all("credit balance" not in item.lower() for item in shown)
    assert all("See service logs" not in item for item in shown)

    rid = _seed_today(warnings=[line], questions=[{"provenance": "linked"}])
    today = TestClient(app).get("/")
    assert today.status_code == 200
    assert "Topic pairing" in today.text
    assert "claude-fable-5" in today.text
    assert "refusal" in today.text.lower() or "refused" in today.text
    assert "See service logs" not in today.text
    assert "req_SECRET" not in today.text

    controls = TestClient(app).get("/controls")
    assert controls.status_code == 200
    assert line in controls.text
    assert "See service logs" not in controls.text
    with session_scope() as session:
        run = session.get(RunRow, rid)
        assert run is not None


def test_wo010_commit_shown(monkeypatch):
    """Red today: /healthz and the footer have no commit; Controls rows have none."""
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abcdef1234567890")
    get_settings.cache_clear()
    try:
        _seed_today(
            warnings=[],
            questions=[{"provenance": "linked"}],
            git_commit="abcdef1234567890",
        )
        health = TestClient(app).get("/healthz").json()
        assert health["commit"] == "abcdef1"
        today = TestClient(app).get("/")
        assert "abcdef1" in today.text
        controls = TestClient(app).get("/controls")
        assert "abcdef1" in controls.text
    finally:
        monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
        get_settings.cache_clear()


def test_wo010_keyed_empty_is_not_template():
    """Red today: keyed scout/cross/smith None still writes template cards."""
    llm = LLM(RunBudget(5.0))
    llm._client = object()
    llm.complete_json = lambda **_k: None  # type: ignore[method-assign]
    signals = [
        Signal(
            source="hacker_news",
            title="Open-weight models undercut retainers",
            url="https://news.ycombinator.com/item?id=1",
            snippet="desks",
            score=12,
            vertical_hints=["ai"],
        )
    ]
    assert run_scouts(signals, llm, run_id=8) == []
    assert run_cross_pollinator(_briefs(3), llm, run_id=8) == []
    assert run_smiths(_briefs(2), [], TasteProfile(), llm, run_id=8)[0] == []
