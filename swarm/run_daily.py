from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from swarm.agents.archivist import render_digest, run_status_from
from swarm.agents.cross_pollinator import run_cross_pollinator
from swarm.agents.curator import run_curator
from swarm.agents.scout import run_scouts
from swarm.agents.smiths import run_smiths
from swarm.budget import RunBudget
from swarm.db import init_db, session_scope
from swarm.dedup import mark_duplicates
from swarm.llm import LLM
from swarm.lock import LockBusy, acquire_lock, release_lock
from swarm.models import (
    Brief,
    Intersection,
    Question,
    QuestionStatus,
    RunStatus,
    Signal,
    SourceHealth,
    StageName,
)
from swarm.orm import (
    BriefRow,
    DigestRow,
    IntersectionRow,
    QuestionRow,
    RunRow,
    SignalRow,
)
from swarm.settings import get_settings
from swarm.sources import (
    BraveSource,
    HackerNewsSource,
    RedditSource,
    WikipediaSource,
    collect_signals,
)
from swarm.taste import load_seed_profile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("swarm")

STAGE_ORDER = [
    StageName.fetch,
    StageName.scout,
    StageName.cross_pollinate,
    StageName.smith,
    StageName.dedup,
    StageName.curate,
    StageName.archive,
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the daily question-engine swarm")
    parser.add_argument("--resume", type=int, default=0, help="Resume this run id")
    parser.add_argument("--force", action="store_true", help="Ignore an existing lock")
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Ping the database and exit. Used by Render to prove the cron's DATABASE_URL.",
    )
    args = parser.parse_args(argv)

    init_db()
    settings = get_settings()
    if args.healthcheck:
        from swarm.db import ping_db

        ping_db()
        print("CRON_HEALTHCHECK_PASS")
        return 0
    run_id = args.resume
    created = False
    if not run_id:
        with session_scope() as session:
            run = RunRow(
                status=RunStatus.running.value,
                budget_usd=settings.budget_usd,
                warnings=[],
                source_health=[],
                stages=[],
            )
            session.add(run)
            session.flush()
            run_id = run.id
            created = True

    try:
        if args.force:
            release_lock()
        acquire_lock(run_id)
    except LockBusy as exc:
        log.error("%s", exc)
        if created:
            with session_scope() as session:
                row = session.get(RunRow, run_id)
                if row:
                    row.status = RunStatus.failed.value
                    row.error = str(exc)
                    row.finished_at = datetime.now(timezone.utc)
        return 2

    try:
        _execute(run_id)
        return 0
    except Exception as exc:  # noqa: BLE001
        log.exception("swarm failed")
        with session_scope() as session:
            row = session.get(RunRow, run_id)
            if row:
                row.status = RunStatus.failed.value
                row.error = f"{type(exc).__name__}: {exc}"
                row.finished_at = datetime.now(timezone.utc)
        return 1
    finally:
        release_lock()


def _execute(run_id: int) -> None:
    settings = get_settings()
    budget = RunBudget(settings.budget_usd)
    llm = LLM(budget)
    taste = load_seed_profile()
    warnings: list[str] = []
    health: list[SourceHealth] = []
    signals: list[Signal] = []
    briefs: list[Brief] = []
    intersections: list[Intersection] = []
    questions: list[Question] = []

    done = _completed_stages(run_id)

    if StageName.fetch.value not in done:
        _set_stage(run_id, StageName.fetch)
        sources = [HackerNewsSource(), RedditSource(), WikipediaSource(), BraveSource()]
        signals, health = _run_async(collect_signals(sources))
        _persist_signals(run_id, signals)
        if not any(h.ok and h.count for h in health):
            warnings.append("all live sources returned nothing; using seeded demo signals")
            signals = _demo_signals()
            _persist_signals(run_id, signals)
        if any(not h.ok for h in health):
            warnings.append("one or more sources failed; run is degraded")
        _checkpoint(run_id, StageName.fetch, health=health, warnings=warnings)
    else:
        signals, health = _load_signals(run_id)
        warnings = _load_warnings(run_id)

    if StageName.scout.value not in done:
        _set_stage(run_id, StageName.scout)
        briefs = run_scouts(signals, llm, run_id=run_id)
        if not briefs:
            raise RuntimeError("scout produced no briefs")
        _persist_briefs(run_id, briefs)
        _checkpoint(run_id, StageName.scout, warnings=warnings)
    else:
        briefs = _load_briefs(run_id)

    if StageName.cross_pollinate.value not in done:
        _set_stage(run_id, StageName.cross_pollinate)
        intersections = run_cross_pollinator(briefs, llm, run_id=run_id)
        _persist_intersections(run_id, intersections)
        _checkpoint(run_id, StageName.cross_pollinate, warnings=warnings)
    else:
        intersections = _load_intersections(run_id)

    if StageName.smith.value not in done:
        _set_stage(run_id, StageName.smith)
        questions = run_smiths(briefs, intersections, taste, llm, run_id=run_id)
        if not questions:
            raise RuntimeError("smiths produced no questions")
        _persist_questions(run_id, questions, replace=True)
        _checkpoint(run_id, StageName.smith, warnings=warnings)
    else:
        questions = _load_questions(run_id)

    if StageName.dedup.value not in done:
        _set_stage(run_id, StageName.dedup)
        prior = _prior_question_texts(run_id, settings.dedup_lookback_days)
        questions = mark_duplicates(questions, prior, threshold=settings.dedup_threshold)
        _persist_questions(run_id, questions, replace=True)
        _checkpoint(run_id, StageName.dedup, warnings=warnings)
    else:
        questions = _load_questions(run_id)

    if StageName.curate.value not in done:
        _set_stage(run_id, StageName.curate)
        questions = run_curator(questions, taste, llm)
        _persist_questions(run_id, questions, replace=True)
        _checkpoint(run_id, StageName.curate, warnings=warnings)
    else:
        questions = _load_questions(run_id)

    if StageName.archive.value not in done:
        _set_stage(run_id, StageName.archive)
        degraded = any(not h.ok for h in health) or any("degraded" in w for w in warnings)
        if not llm.available:
            warnings.append("ANTHROPIC_API_KEY unset — heuristic writer used")
            degraded = True
        else:
            warnings.append(
                f"volume model {settings.anthropic_model}; "
                f"judgment model {settings.judgment_model} "
                f"(cross-pollinator + curator)"
            )
        prior_questions = _prior_curated_questions(run_id)
        doc = render_digest(
            day=date.today(),
            briefs=briefs,
            intersections=intersections,
            questions=questions,
            health=health,
            warnings=warnings,
            degraded=degraded,
            cost_usd=budget.spent_usd,
            prior_questions=prior_questions,
        )
        _persist_digest(run_id, doc)
        status = run_status_from(degraded=degraded, curated_count=doc.curated_count)
        with session_scope() as session:
            row = session.get(RunRow, run_id)
            if row:
                row.status = status.value
                row.finished_at = datetime.now(timezone.utc)
                row.cost_usd = budget.spent_usd
                row.degraded = degraded
                row.warnings = warnings
                row.source_health = [h.model_dump() for h in health]
                row.current_stage = StageName.archive.value
                stages = list(row.stages or [])
                if StageName.archive.value not in stages:
                    stages.append(StageName.archive.value)
                row.stages = stages
        log.info(
            "digest ready date=%s curated=%s killed=%s cost=$%.3f status=%s",
            doc.date,
            doc.curated_count,
            doc.killed_count,
            budget.spent_usd,
            status.value,
        )


def _run_async(coro):  # type: ignore[no-untyped-def]
    import asyncio

    return asyncio.run(coro)


def _completed_stages(run_id: int) -> set[str]:
    with session_scope() as session:
        row = session.get(RunRow, run_id)
        return set(row.stages or []) if row else set()


def _load_warnings(run_id: int) -> list[str]:
    with session_scope() as session:
        row = session.get(RunRow, run_id)
        return list(row.warnings or []) if row else []


def _set_stage(run_id: int, stage: StageName) -> None:
    with session_scope() as session:
        row = session.get(RunRow, run_id)
        if row:
            row.current_stage = stage.value
            row.status = RunStatus.running.value


def _checkpoint(
    run_id: int,
    stage: StageName,
    *,
    health: list[SourceHealth] | None = None,
    warnings: list[str] | None = None,
) -> None:
    with session_scope() as session:
        row = session.get(RunRow, run_id)
        if not row:
            return
        stages = list(row.stages or [])
        if stage.value not in stages:
            stages.append(stage.value)
        row.stages = stages
        row.current_stage = stage.value
        if health is not None:
            row.source_health = [h.model_dump() for h in health]
        if warnings is not None:
            row.warnings = warnings
    log.info("checkpoint %s", stage.value)


def _persist_signals(run_id: int, signals: list[Signal]) -> None:
    with session_scope() as session:
        session.query(SignalRow).filter(SignalRow.run_id == run_id).delete()
        for s in signals:
            session.add(
                SignalRow(
                    run_id=run_id,
                    source=s.source,
                    title=s.title,
                    url=s.url,
                    snippet=s.snippet,
                    score=s.score,
                    vertical_hints=s.vertical_hints,
                    raw=s.raw,
                )
            )


def _persist_briefs(run_id: int, briefs: list[Brief]) -> None:
    with session_scope() as session:
        session.query(BriefRow).filter(BriefRow.run_id == run_id).delete()
        for b in briefs:
            session.add(
                BriefRow(
                    id=b.id,
                    run_id=run_id,
                    vertical=b.vertical,
                    headline=b.headline,
                    what_is_happening=b.what_is_happening,
                    why_now=b.why_now,
                    who_is_affected=b.who_is_affected,
                    velocity=b.velocity.value,
                    sources=b.sources,
                    raw_signals=b.raw_signals,
                    score=b.score,
                )
            )


def _persist_intersections(run_id: int, items: list[Intersection]) -> None:
    with session_scope() as session:
        session.query(IntersectionRow).filter(IntersectionRow.run_id == run_id).delete()
        for i in items:
            session.add(
                IntersectionRow(
                    id=i.id,
                    run_id=run_id,
                    verticals=i.verticals,
                    thesis=i.thesis,
                    surprise=i.surprise,
                    plausibility=i.plausibility,
                    coverage=i.coverage.value,
                    coverage_notes=i.coverage_notes,
                    accepted=i.accepted,
                    reject_reason=i.reject_reason,
                    brief_ids=i.brief_ids,
                )
            )


def _persist_questions(run_id: int, questions: list[Question], *, replace: bool) -> None:
    with session_scope() as session:
        if replace:
            session.query(QuestionRow).filter(QuestionRow.run_id == run_id).delete()
        for q in questions:
            session.add(
                QuestionRow(
                    id=q.id,
                    run_id=run_id,
                    text=q.text,
                    lens=q.lens,
                    verticals=q.verticals,
                    coverage=q.coverage.value,
                    decay_class=q.decay_class.value,
                    status=q.status.value,
                    rank=q.rank,
                    kill_reason=q.kill_reason,
                    duplicate_of=q.duplicate_of,
                    brief_ids=q.brief_ids,
                    intersection_id=q.intersection_id,
                    context=q.context,
                )
            )


def _persist_digest(run_id: int, doc) -> None:  # noqa: ANN001
    with session_scope() as session:
        existing = session.scalar(select(DigestRow).where(DigestRow.date == doc.date))
        if existing:
            existing.run_id = run_id
            existing.title = doc.title
            existing.markdown = doc.markdown
            existing.top_ids = doc.top_ids
            existing.curated_count = doc.curated_count
            existing.killed_count = doc.killed_count
            existing.rejected_intersection_count = doc.rejected_intersection_count
            existing.degraded = doc.degraded
            existing.warnings = doc.warnings
        else:
            session.add(
                DigestRow(
                    run_id=run_id,
                    date=doc.date,
                    title=doc.title,
                    markdown=doc.markdown,
                    top_ids=doc.top_ids,
                    curated_count=doc.curated_count,
                    killed_count=doc.killed_count,
                    rejected_intersection_count=doc.rejected_intersection_count,
                    degraded=doc.degraded,
                    warnings=doc.warnings,
                )
            )


def _load_signals(run_id: int) -> tuple[list[Signal], list[SourceHealth]]:
    with session_scope() as session:
        rows = session.scalars(select(SignalRow).where(SignalRow.run_id == run_id)).all()
        run = session.get(RunRow, run_id)
        signals = [
            Signal(
                source=r.source,
                title=r.title,
                url=r.url,
                snippet=r.snippet,
                score=r.score,
                vertical_hints=r.vertical_hints or [],
                raw=r.raw or {},
            )
            for r in rows
        ]
        health = [SourceHealth.model_validate(h) for h in (run.source_health or [])] if run else []
        return signals, health


def _load_briefs(run_id: int) -> list[Brief]:
    from swarm.models import Velocity

    with session_scope() as session:
        rows = session.scalars(select(BriefRow).where(BriefRow.run_id == run_id)).all()
        return [
            Brief(
                id=r.id,
                vertical=r.vertical,
                headline=r.headline,
                what_is_happening=r.what_is_happening,
                why_now=r.why_now,
                who_is_affected=r.who_is_affected,
                velocity=Velocity(r.velocity),
                sources=r.sources or [],
                raw_signals=r.raw_signals or [],
                score=r.score,
            )
            for r in rows
        ]


def _load_intersections(run_id: int) -> list[Intersection]:
    from swarm.models import Coverage

    with session_scope() as session:
        rows = session.scalars(
            select(IntersectionRow).where(IntersectionRow.run_id == run_id)
        ).all()
        return [
            Intersection(
                id=r.id,
                verticals=r.verticals or [],
                thesis=r.thesis,
                surprise=r.surprise,
                plausibility=r.plausibility,
                coverage=Coverage(r.coverage),
                coverage_notes=r.coverage_notes or "",
                accepted=r.accepted,
                reject_reason=r.reject_reason or "",
                brief_ids=r.brief_ids or [],
            )
            for r in rows
        ]


def _load_questions(run_id: int) -> list[Question]:
    from swarm.models import Coverage, DecayClass

    with session_scope() as session:
        rows = session.scalars(select(QuestionRow).where(QuestionRow.run_id == run_id)).all()
        return [
            Question(
                id=r.id,
                text=r.text,
                lens=r.lens,
                verticals=r.verticals or [],
                coverage=Coverage(r.coverage),
                decay_class=DecayClass(r.decay_class),
                status=QuestionStatus(r.status),
                rank=r.rank,
                kill_reason=r.kill_reason or "",
                duplicate_of=r.duplicate_of,
                brief_ids=r.brief_ids or [],
                intersection_id=r.intersection_id,
                context=r.context or "",
            )
            for r in rows
        ]


def _prior_question_texts(run_id: int, lookback_days: int) -> list[str]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    today = date.today()
    with session_scope() as session:
        today_run_ids: list[int] = []
        for run in session.scalars(select(RunRow)).all():
            started = run.started_at
            if started is None:
                continue
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if started.astimezone(timezone.utc).date() == today:
                today_run_ids.append(run.id)
        rows = session.scalars(
            select(QuestionRow)
            .where(QuestionRow.run_id != run_id)
            .where(QuestionRow.run_id.notin_(today_run_ids or [-1]))
            .where(QuestionRow.status == QuestionStatus.curated.value)
            .where(QuestionRow.created_at >= cutoff)
        ).all()
        return [r.text for r in rows]


def _prior_curated_questions(run_id: int) -> list[Question]:
    """Most recent prior day's curated questions — the near-miss review sample."""
    today = date.today()
    with session_scope() as session:
        prior_run_id: int | None = None
        prior_started: datetime | None = None
        for run in session.scalars(select(RunRow).order_by(RunRow.started_at.desc())).all():
            if run.id == run_id:
                continue
            started = run.started_at
            if started is None:
                continue
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if started.astimezone(timezone.utc).date() == today:
                continue
            if prior_started is None or started > prior_started:
                prior_started = started
                prior_run_id = run.id
        if prior_run_id is None:
            return []
    return [
        q
        for q in _load_questions(prior_run_id)
        if q.status == QuestionStatus.curated
    ]


def _demo_signals() -> list[Signal]:
    """Last-resort fixtures so a total source outage still yields a digest."""
    return [
        Signal(
            source="demo",
            title="Open-weight models undercut enterprise analyst retainers",
            url="https://news.ycombinator.com",
            snippet="Mid-market firms keep buying quarterly strategy decks while local models draft them overnight.",
            score=12,
            vertical_hints=["ai", "business"],
        ),
        Signal(
            source="demo",
            title="Hospital systems refuse to produce model-drafted notes in discovery",
            url="https://en.wikipedia.org/wiki/Electronic_health_record",
            snippet="Malpractice counsel is hitting a wall when the attending's note was a prompt.",
            score=11,
            vertical_hints=["ai", "health"],
        ),
        Signal(
            source="demo",
            title="Cash-pay GLP-1 cohort shows 18-month adherence collapse",
            url="https://en.wikipedia.org/wiki/Semaglutide",
            snippet="Downstream clinics priced as if patients stay; cash-pay users do not.",
            score=14,
            vertical_hints=["health", "business"],
        ),
        Signal(
            source="demo",
            title="Night-shift nursing homes ban cameras after liability memo",
            url="https://en.wikipedia.org/wiki/Nursing_home",
            snippet="AI monitoring vendors keep selling vision; the constraint is counsel, not the model.",
            score=9,
            vertical_hints=["ai", "health"],
        ),
        Signal(
            source="demo",
            title="Regional hospital closures leave Medicaid-ineligible retail clinics",
            url="https://en.wikipedia.org/wiki/Hospital",
            snippet="Towns lose a hospital and gain a clinic that cannot take their patients.",
            score=10,
            vertical_hints=["health", "business"],
        ),
        Signal(
            source="demo",
            title="SEC comment letters start asking about AI-generated 10-K risk factors",
            url="https://www.sec.gov",
            snippet="Issuers cannot say who wrote the risk section when the model cannot testify.",
            score=8,
            vertical_hints=["ai", "business"],
        ),
    ]


if __name__ == "__main__":
    sys.exit(main())
