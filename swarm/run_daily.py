from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from swarm.agents.archivist import lens_label, render_digest, run_status_from
from swarm.agents.cross_pollinator import run_cross_pollinator
from swarm.agents.curator import run_curator
from swarm.agents.desk import run_desk
from swarm.agents.scout import run_scouts
from swarm.agents.smiths import run_smiths
from swarm.budget import RunBudget
from swarm.config import lenses
from swarm.db import init_db, session_scope
from swarm.dedup import mark_duplicates
from swarm.display_time import digest_local_date
from swarm.freshness import freshness_window_days
from swarm.llm import LLM
from swarm.lock import (
    LockBusy,
    acquire_lock,
    fail_unlocked_running_runs,
    held_run_id,
    release_lock,
)
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
from swarm.kills import labelled_kills
from swarm.orm import (
    BriefRow,
    DigestRow,
    IntersectionRow,
    KillReasonRow,
    QuestionRow,
    RunRow,
    SignalRow,
)
from swarm.settings import get_settings
from swarm.sources.base import collect_signals
from swarm.sources.health import annotate_dead_sources
from swarm.sources.registry import build_sources
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
    StageName.desk,
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
    parser.add_argument(
        "--rerender-digest",
        metavar="DATE",
        nargs="?",
        const="latest",
        help="Rewrite an existing digest's markdown from stored artifacts (default: latest).",
    )
    parser.add_argument(
        "--refuse-if-locked",
        action="store_true",
        help=(
            "Exit 1 if a run holds the daily lock so a web preDeploy fails "
            "and the old instance keeps serving. Does not start a run."
        ),
    )
    parser.add_argument(
        "--repair-links",
        action="store_true",
        help="Re-resolve brief URLs from stored scout calls (WO-011). Does not start a run.",
    )
    parser.add_argument(
        "--close-orphans",
        action="store_true",
        help="Fail running rows that do not hold a live lock and drop a stale lock. Does not start a run.",
    )
    parser.add_argument(
        "--backfill-memory",
        action="store_true",
        help="Embed past runs into memory_items once (WO-014). Later deploys skip.",
    )
    parser.add_argument(
        "--rebuild-memory",
        action="store_true",
        help="Drop memory_items and re-embed. Does not touch raw tables.",
    )
    args = parser.parse_args(argv)

    init_db()
    settings = get_settings()
    if args.refuse_if_locked:
        hold = held_run_id()
        if hold is not None:
            print(f"REFUSE_DEPLOY lock held by run {hold}")
            return 1
        print("REFUSE_DEPLOY ok — no live lock")
        if not (
            args.repair_links
            or args.close_orphans
            or args.backfill_memory
            or args.rebuild_memory
        ):
            return 0
    if args.repair_links:
        from swarm.repair_links import repair_past_links

        counts = repair_past_links()
        print(
            "REPAIR_LINKS "
            f"relinked={counts['relinked']} "
            f"unverified={counts['unverified']} "
            f"unlinked={counts['unlinked']} "
            f"skipped={counts.get('skipped', 0)}"
        )
        if not args.close_orphans:
            return 0
    if args.close_orphans:
        closed = fail_unlocked_running_runs()
        print(f"CLOSE_ORPHANS closed={closed}")
    if args.rebuild_memory:
        from swarm.memory.store import rebuild_memory

        counts = rebuild_memory()
        print(f"REBUILD_MEMORY embedded={counts.get('embedded', 0)} ok={int(bool(counts.get('ok')))}")
        if not (args.backfill_memory or args.close_orphans):
            return 0 if counts.get("ok") else 1
    if args.backfill_memory or args.close_orphans:
        from swarm.memory.backfill import backfill_memory

        counts = backfill_memory()
        print(
            "BACKFILL_MEMORY "
            f"embedded={counts.get('embedded', 0)} "
            f"skipped={counts.get('skipped', 0)} "
            f"ok={counts.get('ok', 0)}"
        )
        # preDeploy: --refuse-if-locked already returned 1 if a run holds
        # the lock. Missing Voyage must not fail a deploy after that.
        return 0
    if args.healthcheck:
        from swarm.db import ping_db

        ping_db()
        print("CRON_HEALTHCHECK_PASS")
        return 0
    if args.rerender_digest:
        return _rerender_digest(None if args.rerender_digest == "latest" else args.rerender_digest)
    closed = fail_unlocked_running_runs()
    if closed:
        print(f"CLOSE_ORPHANS closed={closed}")
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
                git_commit=settings.git_commit or "",
            )
            session.add(run)
            session.flush()
            run_id = run.id
            created = True

    try:
        if args.force:
            release_lock()
        acquire_lock(run_id)
        fail_unlocked_running_runs(keep_id=run_id)
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
    llm.run_id = run_id
    taste = load_seed_profile()
    warnings: list[str] = []
    health: list[SourceHealth] = []
    signals: list[Signal] = []
    briefs: list[Brief] = []
    intersections: list[Intersection] = []
    questions: list[Question] = []
    lens_reports: list[dict] = []

    done = _completed_stages(run_id)

    if StageName.fetch.value not in done:
        _set_stage(run_id, StageName.fetch)
        sources = build_sources()
        window = freshness_window_days(
            _last_archived_at(run_id), datetime.now(timezone.utc)
        )
        for src in sources:
            src.freshness_days = window
        signals, health = _run_async(collect_signals(sources))
        health = annotate_dead_sources(health, _prior_source_health(run_id))
        _persist_signals(run_id, signals)
        if not signals:
            if settings.allow_demo_signals:
                log.warning(
                    "ALLOW_DEMO_SIGNALS=true — substituting demo signals. "
                    "These are not today's sources and must not ship from Render."
                )
                warnings.append("ALLOW_DEMO_SIGNALS=true; demo signals substituted")
                signals = _demo_signals()
                _persist_signals(run_id, signals)
            else:
                _checkpoint(run_id, StageName.fetch, health=health, warnings=warnings)
                raise RuntimeError("all sources dark")
        if any(not h.ok for h in health):
            warnings.append("one or more sources failed; run is degraded")
        for h in health:
            if h.dead:
                last = f"; last ok {h.last_ok}" if h.last_ok else ""
                warnings.append(f"{h.source} is dead (consecutive zeros){last}")
        _checkpoint(run_id, StageName.fetch, health=health, warnings=warnings)
    else:
        signals, health = _load_signals(run_id)
        warnings = _load_warnings(run_id)

    if StageName.scout.value not in done:
        _set_stage(run_id, StageName.scout)
        llm.agent = "scout"
        briefs = run_scouts(signals, llm, run_id=run_id)
        if not briefs:
            raise RuntimeError("scout produced no briefs")
        _persist_briefs(run_id, briefs)
        _store_scout_seen(run_id, getattr(run_scouts, "seen_by_source", {}))
        _checkpoint(run_id, StageName.scout, warnings=warnings)
    else:
        briefs = _load_briefs(run_id)

    if StageName.cross_pollinate.value not in done:
        _set_stage(run_id, StageName.cross_pollinate)
        llm.agent = "cross_pollinator"
        intersections = run_cross_pollinator(briefs, llm, run_id=run_id)
        if llm.available and not any(i.accepted for i in intersections):
            pairing = next(
                (line for line in llm.failure_lines if line.startswith("Topic pairing")),
                "No topic pairings this run: no model pairings were returned.",
            )
            if pairing.startswith("Topic pairing"):
                warnings.append(f"No topic pairings this run. {pairing}")
            else:
                warnings.append(pairing)
        for line in getattr(run_cross_pollinator, "passed_over", []) or []:
            if line not in warnings:
                warnings.append(line)
        _persist_intersections(run_id, intersections)
        _checkpoint(run_id, StageName.cross_pollinate, warnings=warnings)
    else:
        intersections = _load_intersections(run_id)

    if StageName.smith.value not in done:
        _set_stage(run_id, StageName.smith)
        llm.agent = "smiths"
        questions, lens_reports = run_smiths(briefs, intersections, taste, llm, run_id=run_id)
        for report in lens_reports:
            if report.get("model_count") == 0 and report.get("reason"):
                warnings.append(
                    f"{lens_label(report['lens'])}: no questions ({report['reason']})"
                )
        if not questions and not any(report.get("reason") for report in lens_reports):
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
        llm.agent = "curator"
        questions = run_curator(questions, taste, llm)
        curated_by = (
            f"model:{settings.judgment_model}" if llm.available else "template"
        )
        _store_curated_by(run_id, curated_by)
        _persist_questions(run_id, questions, replace=True)
        _persist_kill_reasons(run_id, questions)
        _checkpoint(run_id, StageName.curate, warnings=warnings)
    else:
        questions = _load_questions(run_id)

    if StageName.desk.value not in done:
        _set_stage(run_id, StageName.desk)
        llm.agent = "desk"
        run_desk(
            run_id=run_id,
            questions=questions,
            briefs=briefs,
            llm=llm,
            previous_started=_previous_run_started(run_id),
            warnings=warnings,
        )
        _checkpoint(run_id, StageName.desk, warnings=warnings)
        questions = _load_questions(run_id)

    if StageName.archive.value not in done:
        if llm.writer_failed():
            raise RuntimeError(
                "ANTHROPIC_API_KEY is set but every model call failed. "
                "Refusing to archive a heuristic digest. Last error: "
                f"{llm.last_error}"
            )
        _set_stage(run_id, StageName.archive)
        degraded = (
            any(not h.ok for h in health)
            or any(h.dead for h in health)
            or any("degraded" in w for w in warnings)
        )
        warnings.append(f"writer_ok_calls={llm.successes}")
        if not llm.available:
            warnings.append("ANTHROPIC_API_KEY unset — heuristic writer used")
            degraded = True
        elif llm.failures:
            warnings.extend(llm.failure_lines)
            warnings.append(
                f"Anthropic: {llm.successes} ok / {llm.failures} failed "
                f"of {llm.attempts} attempts. Last error: {llm.last_error}"
            )
            degraded = True
        else:
            warnings.append(
                f"writer used Claude ({llm.successes} calls); "
                f"volume={settings.anthropic_model}; "
                f"judgment={settings.judgment_model} "
                f"(cross-pollinator + curator + desk)"
            )
        prior_questions = _prior_curated_questions(run_id)
        started_at, _finished_prior = _run_times(run_id)
        finished_at = datetime.now(timezone.utc)
        day = (
            digest_local_date(started_at, settings.display_tz)
            if started_at is not None
            else date.today()
        )
        status_preview = run_status_from(
            degraded=degraded,
            curated_count=sum(1 for q in questions if q.status == QuestionStatus.curated),
        )
        doc = render_digest(
            day=day,
            briefs=briefs,
            intersections=intersections,
            questions=questions,
            health=health,
            warnings=warnings,
            degraded=degraded,
            cost_usd=budget.spent_usd,
            prior_questions=prior_questions,
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            status=status_preview.value,
            lens_reports=lens_reports,
        )
        _persist_digest(run_id, doc)
        from swarm.memory.store import remember_after_archive

        remember_after_archive(run_id, warnings)
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
                    written_by=b.written_by,
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
                    written_by=i.written_by,
                )
            )


def _persist_kill_reasons(run_id: int, questions: list[Question]) -> None:
    with session_scope() as session:
        session.query(KillReasonRow).filter(KillReasonRow.run_id == run_id).delete()
        for question_id, label, reason in labelled_kills(questions):
            session.add(
                KillReasonRow(
                    question_id=question_id,
                    run_id=run_id,
                    label=label,
                    reason=reason,
                )
            )


def _prior_source_health(run_id: int) -> list[tuple[int, list[dict]]]:
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(RunRow)
                .where(RunRow.id != run_id)
                .order_by(RunRow.id.desc())
                .limit(12)
            )
        )
        return [(r.id, list(r.source_health or [])) for r in rows]


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
                    title=q.title or "",
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
                    provenance=q.provenance,
                    written_by=q.written_by,
                )
            )


def _persist_digest(run_id: int, doc) -> None:  # noqa: ANN001
    payload = dict(
        title=doc.title,
        markdown=doc.markdown,
        top_ids=doc.top_ids,
        curated_count=doc.curated_count,
        killed_count=doc.killed_count,
        rejected_intersection_count=doc.rejected_intersection_count,
        degraded=doc.degraded,
        warnings=doc.warnings,
    )
    with session_scope() as session:
        existing = session.scalar(select(DigestRow).where(DigestRow.run_id == run_id))
        if existing:
            for key, value in payload.items():
                setattr(existing, key, value)
            existing.date = doc.date
            return
        session.add(DigestRow(run_id=run_id, date=doc.date, **payload))


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
                written_by=getattr(r, "written_by", "") or "",
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
                written_by=getattr(r, "written_by", "") or "",
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
                title=getattr(r, "title", "") or "",
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
                provenance=getattr(r, "provenance", "") or "linked",
                written_by=getattr(r, "written_by", "") or "",
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


def _prior_curated_questions(run_id: int, *, as_of: date | None = None) -> list[Question]:
    """Most recent prior day's curated questions — the near-miss review sample."""
    as_of = as_of or date.today()
    with session_scope() as session:
        prior = session.scalar(
            select(DigestRow)
            .where(DigestRow.date < as_of.isoformat())
            .order_by(DigestRow.date.desc(), DigestRow.created_at.desc())
        )
        if not prior or prior.run_id == run_id:
            return []
        prior_run_id = prior.run_id
    return [
        q
        for q in _load_questions(prior_run_id)
        if q.status == QuestionStatus.curated
    ]


def _lens_reports_from_archive(questions: list[Question], warnings: list[str]) -> list[dict]:
    """Rebuild the per-lens header when a stored digest is rewritten."""
    reasons: dict[str, str] = {}
    for warning in warnings:
        marker = ": no questions ("
        if marker not in warning or not warning.endswith(")"):
            continue
        label, rest = warning.split(marker, 1)
        reasons[label.replace("-", "_")] = rest[:-1]
    counts: dict[str, int] = {}
    for question in questions:
        if (question.written_by or "").startswith("model:"):
            counts[question.lens] = counts.get(question.lens, 0) + 1
    return [
        {
            "lens": lens["id"],
            "model_count": counts.get(lens["id"], 0),
            "reason": reasons.get(lens["id"], ""),
        }
        for lens in lenses()
    ]


def _rerender_digest(day: str | None) -> int:
    """Rewrite stored markdown so a download matches the current archivist."""
    with session_scope() as session:
        if day:
            row = session.scalar(
                select(DigestRow)
                .where(DigestRow.date == day)
                .order_by(DigestRow.created_at.desc(), DigestRow.id.desc())
            )
        else:
            row = session.scalar(
                select(DigestRow).order_by(
                    DigestRow.created_at.desc(), DigestRow.id.desc()
                )
            )
        if not row:
            print("no digest to rerender", file=sys.stderr)
            return 1
        run_id = row.run_id
        digest_day = date.fromisoformat(row.date)
        run = session.get(RunRow, run_id)
        cost = run.cost_usd if run else 0.0
        degraded = bool(row.degraded)
        warnings = list(row.warnings or [])
        health = (
            [SourceHealth.model_validate(h) for h in (run.source_health or [])]
            if run
            else []
        )

    briefs = _load_briefs(run_id)
    intersections = _load_intersections(run_id)
    questions = _load_questions(run_id)
    prior = _prior_curated_questions(run_id, as_of=digest_day)
    doc = render_digest(
        day=digest_day,
        briefs=briefs,
        intersections=intersections,
        questions=questions,
        health=health,
        warnings=warnings,
        degraded=degraded,
        cost_usd=cost,
        prior_questions=prior,
        lens_reports=_lens_reports_from_archive(questions, warnings),
    )
    _persist_digest(run_id, doc)
    print(f"RERENDER_DIGEST_OK {doc.date} near_miss={len(doc.near_miss_pairs)}")
    return 0


def _store_scout_seen(run_id: int, seen: dict) -> None:
    with session_scope() as session:
        row = session.get(RunRow, run_id)
        if row:
            row.scout_seen = dict(seen or {})


def _store_curated_by(run_id: int, curated_by: str) -> None:
    with session_scope() as session:
        row = session.get(RunRow, run_id)
        if row:
            row.curated_by = curated_by


def _previous_run_started(run_id: int) -> datetime | None:
    with session_scope() as session:
        row = session.scalar(
            select(RunRow).where(RunRow.id < run_id).order_by(RunRow.id.desc())
        )
        return row.started_at if row else None


def _run_times(run_id: int) -> tuple[datetime | None, datetime | None]:
    with session_scope() as session:
        row = session.get(RunRow, run_id)
        if not row:
            return None, None
        return row.started_at, row.finished_at


def _last_archived_at(run_id: int) -> datetime | None:
    with session_scope() as session:
        row = session.scalar(
            select(RunRow)
            .join(DigestRow, DigestRow.run_id == RunRow.id)
            .where(RunRow.id != run_id)
            .order_by(RunRow.id.desc())
        )
        if not row:
            return None
        return row.finished_at or row.started_at


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
