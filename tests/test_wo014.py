"""WO-014 slice A: memory index, desk recall, search. Fixtures only — no Voyage."""

from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ["EMBED_MODEL"] = "voyage-4"
os.environ["EMBED_DIMS"] = "8"

import pytest
from fastapi.testclient import TestClient

from dashboard.main import app
from swarm.db import init_db, session_scope
from swarm.orm import (
    BriefRow,
    DigestRow,
    IntersectionRow,
    OpportunityRow,
    OpportunityVerdictRow,
    QuestionRow,
    RunRow,
)
from swarm.settings import get_settings

get_settings.cache_clear()


@pytest.fixture(scope="module", autouse=True)
def _wo014_embed_settings():
    os.environ["EMBED_MODEL"] = "voyage-4"
    os.environ["EMBED_DIMS"] = "8"
    get_settings.cache_clear()
    yield
    os.environ.pop("EMBED_DIMS", None)
    os.environ.pop("MEMORY_SEARCHES_PER_DAY", None)
    get_settings.cache_clear()


def _vec(tag: float, dims: int = 8) -> list[float]:
    # Small planted vectors. Tests never call Voyage.
    out = [0.0] * dims
    out[0] = tag
    out[1] = 1.0
    n = sum(x * x for x in out) ** 0.5
    return [x / n for x in out]


def _seed_run(run_id: int, day: str) -> None:
    started = datetime.fromisoformat(day + "T12:00:00+00:00")
    with session_scope() as session:
        if session.get(RunRow, run_id) is None:
            session.add(
                RunRow(
                    id=run_id,
                    status="ok",
                    started_at=started,
                    finished_at=started,
                    git_commit="test014",
                )
            )


def _plant_catalog() -> None:
    """A tiny history the seven tests share. Distinctive wo014- ids."""
    init_db()
    _seed_run(1401, "2026-09-15")
    _seed_run(1402, "2026-10-02")
    with session_scope() as session:
        if session.get(QuestionRow, "wo014-q-old") is None:
            session.add(
                QuestionRow(
                    id="wo014-q-old",
                    run_id=1401,
                    text="If GLP-1 prices fall, who owns the titration protocol?",
                    title="GLP-1 titration",
                    lens="opportunity",
                    status="curated",
                    verticals=["health"],
                    created_at=datetime(2026, 9, 15, tzinfo=timezone.utc),
                )
            )
        if session.get(BriefRow, "wo014-b-old") is None:
            session.add(
                BriefRow(
                    id="wo014-b-old",
                    run_id=1401,
                    vertical="health",
                    headline="GLP-1 cash-pay clinics",
                    what_is_happening="Cash-pay clinics are rewriting titration after list-price cuts.",
                    sources=["https://example.test/glp1"],
                )
            )
        if session.get(IntersectionRow, "wo014-i-old") is None:
            session.add(
                IntersectionRow(
                    id="wo014-i-old",
                    run_id=1401,
                    verticals=["health", "education"],
                    thesis="The earnings rule 425.112 is the unglamorous gate on program eligibility.",
                    accepted=True,
                )
            )
        if session.get(OpportunityRow, "wo014-opp-old") is None:
            session.add(
                OpportunityRow(
                    id="wo014-opp-old",
                    run_id=1401,
                    question_id="wo014-q-old",
                    status="completed",
                    whats_actually_true="Cash-pay GLP-1 clinics need a titration list, not a new molecule.",
                    picked_shape="list",
                    latest_verdict="park",
                    latest_verdict_why="wait for the price cut to stick",
                )
            )
        if session.query(OpportunityVerdictRow).filter_by(
            opportunity_id="wo014-opp-old"
        ).first() is None:
            session.add(
                OpportunityVerdictRow(
                    opportunity_id="wo014-opp-old",
                    verdict="park",
                    why="wait for the price cut to stick",
                )
            )
        if session.get(DigestRow, 1401) is None:
            session.add(
                DigestRow(
                    id=1401,
                    run_id=1401,
                    date="2026-09-15",
                    title="Question Engine — 2026-09-15",
                    markdown="seed",
                    curated_count=1,
                )
            )
        if session.get(QuestionRow, "wo014-q-today") is None:
            session.add(
                QuestionRow(
                    id="wo014-q-today",
                    run_id=1402,
                    text="Who sells the first titration protocol after today's GLP-1 cut?",
                    title="Today's titration",
                    lens="opportunity",
                    status="curated",
                    verticals=["health"],
                    created_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
                )
            )


def test_rebuild_leaves_raw_tables_untouched():
    """RED until memory_items exists and --rebuild-memory is a no-op on raw rows."""
    from swarm.memory.embed import use_embedder
    from swarm.memory.store import rebuild_memory, search_memory
    from swarm.orm import MemoryItemRow

    _plant_catalog()
    use_embedder(lambda texts, **_k: [_vec(0.2) for _ in texts])

    first = rebuild_memory()
    assert first["embedded"] >= 4
    with session_scope() as session:
        before_q = session.get(QuestionRow, "wo014-q-old").text
        before_b = session.get(BriefRow, "wo014-b-old").headline
        before_n = session.query(MemoryItemRow).count()
        session.query(MemoryItemRow).delete()
        after_wipe = session.query(MemoryItemRow).count()
    assert after_wipe == 0

    second = rebuild_memory()
    assert second["embedded"] == first["embedded"]
    with session_scope() as session:
        assert session.get(QuestionRow, "wo014-q-old").text == before_q
        assert session.get(BriefRow, "wo014-b-old").headline == before_b
        assert session.query(MemoryItemRow).count() == before_n
    # Smoke: the catalog is queryable after rebuild.
    assert search_memory("GLP-1")["results"]


def test_queries_never_compare_another_model():
    from swarm.memory.embed import use_embedder
    from swarm.memory.store import index_item, search_memory
    from swarm.orm import MemoryItemRow

    init_db()
    use_embedder(lambda texts, **_k: [_vec(0.9) for _ in texts])
    index_item(
        kind="brief",
        ref_id="wo014-other-model",
        text="A stray row from voyage-3-lite about GLP-1s.",
        run_id=1401,
        item_date="2026-09-15",
        title="old model",
        embed_model="voyage-3-lite",
        embed_dims=8,
        embedding=_vec(0.99),
    )
    index_item(
        kind="brief",
        ref_id="wo014-current-model",
        text="Current-model brief on something else entirely.",
        run_id=1401,
        item_date="2026-09-15",
        title="current model",
        embed_model=get_settings().embed_model,
        embed_dims=get_settings().embed_dims,
        embedding=_vec(0.1),
    )
    hits = search_memory("GLP-1")["results"]
    ids = {h["ref_id"] for h in hits}
    assert "wo014-other-model" not in ids
    with session_scope() as session:
        stray = (
            session.query(MemoryItemRow)
            .filter_by(ref_id="wo014-other-model")
            .one()
        )
        assert stray.embed_model == "voyage-3-lite"


def test_memory_failure_does_not_block_the_digest():
    from swarm.memory.embed import use_embedder
    from swarm.memory.store import embed_run, pending_ref_ids, remember_after_archive
    from swarm.orm import MemoryItemRow

    _plant_catalog()
    with session_scope() as session:
        session.query(MemoryItemRow).filter(MemoryItemRow.run_id == 1402).delete()
    with session_scope() as session:
        if session.get(DigestRow, 1402) is None:
            session.add(
                DigestRow(
                    id=1402,
                    run_id=1402,
                    date="2026-10-02",
                    title="Question Engine — 2026-10-02",
                    markdown="archived before memory",
                    curated_count=1,
                    warnings=[],
                )
            )

    def _boom(_texts, **_k):
        raise RuntimeError("voyage 429")

    use_embedder(_boom)
    warnings: list[str] = []
    remember_after_archive(1402, warnings)
    assert any("memory not updated" in w for w in warnings)
    with session_scope() as session:
        digest = session.get(DigestRow, 1402)
        assert digest is not None
        assert "archived before memory" in (digest.markdown or "")
        assert "memory not updated" in " ".join(digest.warnings or [])
        leftover = (
            session.query(MemoryItemRow)
            .filter(MemoryItemRow.run_id == 1402)
            .count()
        )
    assert leftover == 0
    assert "wo014-q-today" in pending_ref_ids()

    use_embedder(lambda texts, **_k: [_vec(0.3) for _ in texts])
    result = embed_run(1402)
    assert result["embedded"] >= 1
    assert "wo014-q-today" not in pending_ref_ids()


def test_recall_is_dated_excludes_this_run_and_labels_the_prompt():
    from swarm.memory.embed import use_embedder
    from swarm.memory.recall import format_for_prompt, recall_for_desk
    from swarm.memory.store import rebuild_memory

    _plant_catalog()
    use_embedder(lambda texts, **_k: [_vec(0.4) for _ in texts])
    rebuild_memory()

    related = recall_for_desk(
        text="Who sells a GLP-1 titration list?",
        run_id=1402,
    )
    assert related, "expected a past card or verdict"
    assert all(item["run_id"] != 1402 for item in related)
    first = related[0]
    assert first["item_date"]
    assert first.get("verdict") == "park"
    assert "price cut" in (first.get("verdict_why") or "")

    prompt = format_for_prompt(related)
    assert "past" in prompt.lower()
    assert "not current fact" in prompt.lower()
    assert "Killed" in prompt
    assert "Parked" in prompt


def test_exact_rule_number_beats_a_closer_vector():
    from swarm.memory.embed import use_embedder
    from swarm.memory.store import index_item, search_memory

    init_db()
    get_settings()
    use_embedder(lambda texts, **_k: [_vec(0.0) for _ in texts])
    index_item(
        kind="brief",
        ref_id="wo014-meaning",
        text="Insulin pricing and pharmacy benefit managers after a list-price cut.",
        run_id=1401,
        item_date="2026-09-15",
        title="insulin PBMs",
        verticals=["health"],
        embedding=_vec(0.99),
    )
    index_item(
        kind="intersection",
        ref_id="wo014-rule",
        text="The earnings rule 425.112 is the unglamorous gate on program eligibility.",
        run_id=1401,
        item_date="2026-09-15",
        title="earnings rule",
        verticals=["education"],
        embedding=_vec(0.01),
    )
    hits = search_memory("425.112")["results"]
    assert hits
    assert hits[0]["ref_id"] == "wo014-rule"


def test_backfill_runs_once_and_records_the_marker():
    from swarm.memory.backfill import MARKER, backfill_already_ran, backfill_memory
    from swarm.memory.embed import use_embedder
    from swarm.orm import BriefRow, DeployMarkerRow, MemoryItemRow

    _plant_catalog()
    use_embedder(lambda texts, **_k: [_vec(0.2) for _ in texts])
    with session_scope() as session:
        existing = session.get(DeployMarkerRow, MARKER)
        if existing is not None:
            session.delete(existing)
        session.query(MemoryItemRow).delete()

    first = backfill_memory()
    assert first["skipped"] == 0
    assert first["embedded"] >= 1
    assert backfill_already_ran() is True

    with session_scope() as session:
        planted = session.get(BriefRow, "wo014-b-old")
        planted.headline = "should not be re-read on a second backfill"

    second = backfill_memory()
    assert second["skipped"] == 1
    assert second["embedded"] == 0


def test_search_cap_holds():
    from swarm.memory.search_cap import (
        force_day,
        remaining_searches,
        reset_day,
        take_search,
    )

    init_db()
    os.environ["MEMORY_SEARCHES_PER_DAY"] = "2"
    get_settings.cache_clear()

    reset_day("2099-01-01")
    assert take_search(day="2099-01-01") is True
    assert take_search(day="2099-01-01") is True
    assert take_search(day="2099-01-01") is False
    assert remaining_searches(day="2099-01-01") == 0

    reset_day("2099-01-02")
    force_day("2099-01-02")
    client = TestClient(app)
    r1 = client.get("/archive", params={"mq": "GLP-1"})
    r2 = client.get("/archive", params={"mq": "earnings rule"})
    r3 = client.get("/archive", params={"mq": "again"})
    force_day(None)
    os.environ.pop("MEMORY_SEARCHES_PER_DAY", None)
    get_settings.cache_clear()
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert "Search memory cap" in r3.text or "daily cap" in r3.text.lower()


def test_search_memory_names_missing_voyage_key(monkeypatch):
    """Empty catalog is a missing key, not a failed search."""
    init_db()
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    get_settings.cache_clear()
    client = TestClient(app)
    page = client.get("/archive")
    assert page.status_code == 200
    assert "VOYAGE_API_KEY" in page.text
    assert "missing" in page.text.lower()
    page2 = client.get("/archive", params={"mq": "GLP-1"})
    assert page2.status_code == 200
    assert "VOYAGE_API_KEY" in page2.text
    assert "Nothing in memory matches" not in page2.text
