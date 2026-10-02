from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from swarm.config import lenses, verticals
from swarm.db import init_db, ping_db, session_scope
from swarm.dedup import sample_near_miss_pairs
from swarm.lock import current_lock
from swarm.publish_gate import gate_reasons, publish_gate_open
from swarm.staleness import digest_age_days, is_stale, last_run_label
from swarm.models import Coverage, DecayClass, Question, QuestionStatus
from swarm.desk.assets import HEADINGS as ASSET_HEADINGS
from swarm.desk.assets import load_assets, save_assets
from swarm.desk.verdicts import apply_verdict, verdict_history
from swarm.orm import (
    BriefRow,
    DigestRow,
    IntersectionRow,
    IssueRow,
    OpportunityRow,
    QuestionRow,
    RatingRow,
    RunRow,
    SignalRow,
)
from swarm.display import (
    age_days_from,
    format_local,
    run_banner,
    run_stamp,
)
from swarm.settings import get_settings
from dashboard.public_text import public_page_text, public_run_error, public_warning
from dashboard.run_limits import (
    mark_accepted,
    refuse_if_cooling_down,
    refuse_if_over_ceiling,
    run_control,
    stage_words,
)
from dashboard.honesty import (
    UNRECORDED,
    bank_groups,
    fetch_counts,
    from_cites,
    from_line,
    model_written_line,
    scout_seen,
    pairing_reason,
    banned_words_line,
    sources_linked_line,
    sources_read_line,
    split_warnings,
    failure_lines_from_warnings,
)
from swarm.primary import domain_of
from swarm.taste import load_seed_profile, load_taste, steering_label
from swarm.voice import voice_is_filled

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
log = logging.getLogger("dashboard")

_run_thread: threading.Thread | None = None
_run_lock = threading.Lock()
_issue_thread: threading.Thread | None = None
_issue_lock = threading.Lock()

PUBLIC_PATHS = {"/health", "/healthz"}
_SPEND_PATHS = {"/api/run", "/api/issues"}
_COOKIE_NAME = "access_token"


def _provided_token(request: Request) -> str:
    """Header, then query, then cookie. Query must beat a stale cookie."""
    header = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    query = (request.query_params.get("token") or "").strip()
    cookie = (request.cookies.get(_COOKIE_NAME) or "").strip()
    return header or query or cookie


def _unauthorized() -> HTMLResponse:
    return HTMLResponse("Unauthorized", status_code=401)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    if settings.dashboard_auth_enabled:
        log.info("DASHBOARD_AUTH=%s — token gate is on", settings.dashboard_auth)
    else:
        log.info(
            "DASHBOARD_AUTH=off. MAX_RUNS_PER_DAY=%s RUN_COOLDOWN_SECONDS=%s",
            settings.max_runs_per_day,
            settings.run_cooldown_seconds,
        )
    init_db()
    yield


app = FastAPI(title="Question Engine", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


def _is_public(path: str) -> bool:
    cleaned = path.rstrip("/") or "/"
    return cleaned in PUBLIC_PATHS or path in PUBLIC_PATHS


@app.middleware("http")
async def access_gate(request: Request, call_next):
    settings = get_settings()
    path = request.url.path

    if not settings.dashboard_auth_enabled:
        response = await call_next(request)
        if _COOKIE_NAME in request.cookies:
            response.delete_cookie(_COOKIE_NAME)
        return response

    if _is_public(path):
        return await call_next(request)

    token = settings.auth_token
    provided = _provided_token(request)
    spend = request.method == "POST" and (
        path in _SPEND_PATHS or path.endswith("/assay")
    )

    if not token and not settings.allow_unauthenticated:
        return _unauthorized()

    if spend:
        if token and provided != token:
            return _unauthorized()
    elif not settings.allow_unauthenticated and (not token or provided != token):
        return _unauthorized()

    response = await call_next(request)
    query_token = (request.query_params.get("token") or "").strip()
    if token and query_token == token:
        response.set_cookie(_COOKIE_NAME, token, httponly=True, samesite="lax")
    return response


@app.get("/health")
@app.get("/healthz")
def health() -> dict:
    db_ok = False
    try:
        db_ok = ping_db()
    except Exception:
        db_ok = False
    return {
        "ok": db_ok,
        "database": db_ok,
        "pgvector_installed": False,
        "dedup": "lexical",
        "commit": get_settings().short_commit or get_settings().git_commit or "",
    }


def _latest_digest() -> DigestRow | None:
    with session_scope() as session:
        row = session.scalar(
            select(DigestRow).order_by(DigestRow.created_at.desc(), DigestRow.id.desc())
        )
        if row:
            session.expunge(row)
        return row


def _active_run() -> RunRow | None:
    with session_scope() as session:
        row = session.scalar(
            select(RunRow)
            .where(RunRow.status == "running")
            .order_by(RunRow.started_at.desc())
        )
        if row:
            session.expunge(row)
        return row


def _question_from_row(row: QuestionRow) -> Question:
    return Question(
        id=row.id,
        text=row.text,
        title=getattr(row, "title", "") or "",
        lens=row.lens,
        verticals=list(row.verticals or []),
        coverage=Coverage(row.coverage) if row.coverage else Coverage.unknown,
        decay_class=DecayClass(row.decay_class) if row.decay_class else DecayClass.slow,
        status=QuestionStatus(row.status),
        rank=row.rank,
        kill_reason=row.kill_reason or "",
        duplicate_of=row.duplicate_of,
        brief_ids=list(row.brief_ids or []),
        intersection_id=row.intersection_id,
        context=row.context or "",
        provenance=getattr(row, "provenance", "") or "",
        written_by=getattr(row, "written_by", "") or "",
        promoted_at=getattr(row, "promoted_at", None),
    )


def _prior_day_curated(current_date: str | None) -> list[Question]:
    if not current_date:
        return []
    with session_scope() as session:
        prior = session.scalar(
            select(DigestRow)
            .where(DigestRow.date < current_date)
            .order_by(DigestRow.date.desc(), DigestRow.created_at.desc())
        )
        if not prior:
            return []
        rows = list(
            session.scalars(
                select(QuestionRow)
                .where(QuestionRow.run_id == prior.run_id)
                .where(QuestionRow.status == "curated")
            ).all()
        )
        return [_question_from_row(r) for r in rows]


def _read_line(run: RunRow | None) -> str:
    if run is None:
        return ""
    seen = dict(run.scout_seen or {})
    parts: list[str] = []
    for item in run.source_health or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("source") or "")
        fetched = item.get("count", 0)
        if name in seen:
            parts.append(f"{name}: {fetched} fetched, {seen[name]} read")
        else:
            parts.append(f"{name}: {fetched} fetched")
    return " · ".join(parts)


def _nav_ctx(request: Request, page: str) -> dict:
    return {
        "request": request,
        "page": page,
        "active_run": _active_run(),
        "git_commit": get_settings().short_commit,
        "assay_estimate": get_settings().desk_cost_estimate_usd,
    }


def _opportunity_view(row: OpportunityRow) -> dict:
    title = ""
    with session_scope() as session:
        q = session.get(QuestionRow, row.question_id)
        if q:
            title = q.title or q.text[:80]
    return {
        "id": row.id,
        "run_id": row.run_id,
        "question_id": row.question_id,
        "question_title": title,
        "status": row.status,
        "claims": row.claims or [],
        "whats_actually_true": row.whats_actually_true,
        "shapes": row.shapes or [],
        "picked_shape": row.picked_shape,
        "who_has_problem": row.who_has_problem,
        "who_pays": row.who_pays,
        "what_they_use_today": row.what_they_use_today,
        "why_now": row.why_now,
        "how_it_charges": row.how_it_charges,
        "rivals": row.rivals,
        "first_prospects": row.first_prospects or [],
        "fit": row.fit,
        "weekend_test": row.weekend_test,
        "why_it_might_fail": row.why_it_might_fail,
        "red_flags": row.red_flags or [],
        "check_note": row.check_note,
        "cost_usd": row.cost_usd,
        "written_by": row.written_by,
        "latest_verdict": row.latest_verdict,
        "latest_verdict_why": row.latest_verdict_why,
        "verdict_history": verdict_history(row.id),
    }


def _desk_line(run_id: int | None, warnings: list[str] | None) -> tuple[str, str]:
    skipped = ""
    for raw in warnings or []:
        text = str(raw)
        if text.startswith("Opportunity desk skipped") or text.startswith(
            "Opportunity desk stopped"
        ):
            skipped = text
    if run_id is None:
        return "", skipped
    with session_scope() as session:
        rows = list(
            session.query(OpportunityRow)
            .filter(OpportunityRow.run_id == run_id)
            .order_by(OpportunityRow.created_at.desc())
        )
        for row in rows:
            session.expunge(row)
    if not rows:
        return "", skipped
    total = sum(float(r.cost_usd or 0) for r in rows)
    line = f"Opportunity desk ${total:.2f} ({len(rows)} card{'s' if len(rows) != 1 else ''})"
    return line, skipped


@app.get("/", response_class=HTMLResponse)
def today(request: Request):
    digest = _latest_digest()
    questions: list[QuestionRow] = []
    ratings: dict[str, int] = {}
    rating_whys: dict[str, str] = {}
    intersections: list[IntersectionRow] = []
    run: RunRow | None = None
    if digest:
        with session_scope() as session:
            run = session.get(RunRow, digest.run_id)
            questions = list(
                session.scalars(
                    select(QuestionRow)
                    .where(QuestionRow.run_id == digest.run_id)
                    .where(QuestionRow.status.in_(["curated", "killed", "duplicate"]))
                ).all()
            )
            qids = [q.id for q in questions]
            if qids:
                for r in session.scalars(
                    select(RatingRow).where(RatingRow.question_id.in_(qids))
                ):
                    ratings[r.question_id] = r.stars
                    rating_whys[r.question_id] = r.why or ""
            intersections = list(
                session.scalars(
                    select(IntersectionRow).where(IntersectionRow.run_id == digest.run_id)
                ).all()
            )
            briefs = list(
                session.scalars(
                    select(BriefRow).where(BriefRow.run_id == digest.run_id)
                ).all()
            )
            signals = list(
                session.scalars(
                    select(SignalRow).where(SignalRow.run_id == digest.run_id)
                ).all()
            )
            if run:
                session.expunge(run)
            for q in questions:
                session.expunge(q)
            for i in intersections:
                session.expunge(i)
            for b in briefs:
                session.expunge(b)
            for s in signals:
                session.expunge(s)
    else:
        briefs = []
        signals = []
    curated = sorted(
        [q for q in questions if q.status == "curated"],
        key=lambda q: q.rank or 99,
    )
    killed = [q for q in questions if q.status == "killed"]
    duplicates = [q for q in questions if q.status == "duplicate"]
    accepted = [i for i in intersections if i.accepted]
    rejected = [i for i in intersections if not i.accepted]
    top_ids = set(digest.top_ids or []) if digest else set()
    top = [q for q in curated if q.id in top_ids] or curated[:5]
    bank = [q for q in curated if q not in top]
    prior_curated = _prior_day_curated(digest.date if digest else None)
    briefs_for_pairs = {b.id: b for b in briefs}
    missing = {
        bid
        for q in prior_curated
        for bid in (q.brief_ids or [])
        if bid not in briefs_for_pairs
    }
    if missing:
        with session_scope() as session:
            for brief in session.scalars(select(BriefRow).where(BriefRow.id.in_(missing))):
                session.expunge(brief)
                briefs_for_pairs[brief.id] = brief
    near_miss = sample_near_miss_pairs(
        [_question_from_row(q) for q in curated],
        prior_curated,
        briefs_by_id=briefs_for_pairs,
    )
    settings = get_settings()
    _profile, taste_source = load_taste()
    finished = run.finished_at if run else None
    age_days = age_days_from(finished)
    if age_days is None and digest:
        age_days = digest_age_days(digest.date)
    banner = ""
    stamps: dict[str, str] = {}
    if run:
        banner = run_banner(
            run_id=run.id,
            started=run.started_at,
            finished=run.finished_at,
            cost_usd=run.cost_usd or 0.0,
            status=run.status or "",
        )
        stamp = run_stamp(run.id, run.started_at)
        stamps = {q.id: stamp for q in questions}
    briefs_by_id = {b.id: b for b in briefs}
    signals_by_url = {s.url: s for s in signals if getattr(s, "url", "")}
    from_lines = {q.id: from_line(q, briefs_by_id, signals_by_url) for q in questions}
    cites = {q.id: from_cites(q, briefs_by_id, signals_by_url) for q in questions}
    url_domains = {s.url: domain_of(s.url) for s in signals if getattr(s, "url", "")}
    for brief in briefs:
        for url in getattr(brief, "sources", None) or []:
            if url and url not in url_domains:
                url_domains[url] = domain_of(url)
    fetched = fetch_counts(signals)
    seen = scout_seen(signals)
    bank_by_vertical = bank_groups(bank)
    if digest and digest.warnings:
        digest.warnings = [public_warning(str(w)) for w in digest.warnings]
    page_warnings, debug_lines = split_warnings(digest.warnings if digest else None)
    saved: list[QuestionRow] = []
    with session_scope() as session:
        saved = list(
            session.scalars(
                select(QuestionRow)
                .where(QuestionRow.promoted.is_(True))
                .order_by(QuestionRow.promoted_at.desc())
                .limit(5)
            )
        )
        for row in saved:
            session.expunge(row)
    linked_line, linked_warn = sources_linked_line(questions, briefs_by_id)
    return templates.TemplateResponse(
        request,
        "today.html",
        {
            **_nav_ctx(request, "today"),
            "digest": digest,
            "run": run,
            "run_banner": banner,
            "run_stamps": stamps,
            "top": top,
            "bank": bank,
            "bank_by_vertical": bank_by_vertical,
            "killed": killed[:6],
            "accepted": accepted,
            "rejected": rejected,
            "ratings": ratings,
            "rating_whys": rating_whys,
            "from_lines": from_lines,
            "from_cites": cites,
            "url_domains": url_domains,
            "fetch_counts": fetched,
            "scout_seen": seen,
            "briefs": briefs,
            "unrecorded": UNRECORDED,
            "duplicate_count": len(duplicates),
            "question_count": len(questions),
            "near_miss": near_miss,
            "has_prior_day": bool(prior_curated),
            "last_run_label": last_run_label(age_days) if age_days is not None else None,
            "digest_stale": is_stale(age_days, settings.stale_after_days)
            if age_days is not None
            else False,
            "stale_after_days": settings.stale_after_days,
            "taste_steering": steering_label(taste_source),
            "run_control": {
                **run_control(),
                "stage_words": stage_words(run.current_stage) if run else "",
            },
            "model_written_line": model_written_line(questions),
            "sources_read_line": _read_line(run) or sources_read_line(fetched),
            "page_warnings": page_warnings,
            "debug_lines": debug_lines,
            "saved": saved,
            "sources_linked_line": linked_line,
            "sources_linked_warn": linked_warn,
            "banned_words_line": banned_words_line(questions, intersections),
            "pairing_reason": pairing_reason(page_warnings + debug_lines),
            "opportunities": _run_opportunities(digest.run_id if digest else None),
            "desk_line": _desk_line(
                digest.run_id if digest else None,
                digest.warnings if digest else None,
            )[0],
            "desk_skipped": _desk_line(
                digest.run_id if digest else None,
                digest.warnings if digest else None,
            )[1],
        },
    )


def _run_opportunities(run_id: int | None) -> list[dict]:
    if run_id is None:
        return []
    with session_scope() as session:
        rows = list(
            session.query(OpportunityRow)
            .filter(OpportunityRow.run_id == run_id)
            .order_by(OpportunityRow.created_at.desc())
        )
        for row in rows:
            session.expunge(row)
    return [_opportunity_view(r) for r in rows]


@app.get("/archive", response_class=HTMLResponse)
def archive(
    request: Request,
    q: str = "",
    lens: str = "",
    vertical: str = "",
    coverage: str = "",
    rating: str = "",
    saved: str = "",
):
    with session_scope() as session:
        stmt = select(QuestionRow)
        if saved:
            stmt = stmt.where(QuestionRow.promoted.is_(True))
        else:
            stmt = stmt.where(QuestionRow.status == "curated")
        if q:
            stmt = stmt.where(QuestionRow.text.ilike(f"%{q}%"))
        if lens:
            stmt = stmt.where(QuestionRow.lens == lens)
        if coverage:
            stmt = stmt.where(QuestionRow.coverage == coverage)
        rows = list(session.scalars(stmt.order_by(QuestionRow.created_at.desc())).all())
        if vertical:
            rows = [r for r in rows if vertical in (r.verticals or [])]
        rating_rows = list(session.scalars(select(RatingRow)).all())
        rating_map = {r.question_id: r.stars for r in rating_rows}
        rating_whys = {r.question_id: r.why or "" for r in rating_rows}
        if rating.isdigit():
            want = int(rating)
            rows = [r for r in rows if rating_map.get(r.id) == want]
        digests = list(
            session.scalars(
                select(DigestRow).order_by(
                    DigestRow.date.desc(), DigestRow.created_at.desc()
                )
            ).all()
        )
        run_ids = {r.run_id for r in rows}
        runs_by_id = {}
        if run_ids:
            for run in session.scalars(select(RunRow).where(RunRow.id.in_(run_ids))):
                runs_by_id[run.id] = run
        stamps = {
            r.id: run_stamp(r.run_id, runs_by_id[r.run_id].started_at)
            if r.run_id in runs_by_id
            else f"run {r.run_id}"
            for r in rows
        }
        brief_ids = {bid for r in rows for bid in (r.brief_ids or [])}
        briefs_by_id: dict[str, BriefRow] = {}
        if brief_ids:
            for brief in session.scalars(
                select(BriefRow).where(BriefRow.id.in_(brief_ids))
            ):
                briefs_by_id[brief.id] = brief
                session.expunge(brief)
        signals_by_url: dict[str, SignalRow] = {}
        if brief_ids:
            run_ids_for_briefs = {b.run_id for b in briefs_by_id.values()}
            if run_ids_for_briefs:
                for sig in session.scalars(
                    select(SignalRow).where(SignalRow.run_id.in_(run_ids_for_briefs))
                ):
                    if sig.url:
                        signals_by_url[sig.url] = sig
                        session.expunge(sig)
        from_lines = {
            r.id: from_line(r, briefs_by_id, signals_by_url) for r in rows
        }
        cites = {
            r.id: from_cites(r, briefs_by_id, signals_by_url) for r in rows
        }
        for r in rows:
            session.expunge(r)
        for d in digests:
            session.expunge(d)
    return templates.TemplateResponse(
        request,
        "archive.html",
        {
            **_nav_ctx(request, "archive"),
            "questions": rows,
            "digests": digests,
            "ratings": rating_map,
            "rating_whys": rating_whys,
            "run_stamps": stamps,
            "from_lines": from_lines,
            "from_cites": cites,
            "unrecorded": UNRECORDED,
            "q": q,
            "lens": lens,
            "vertical": vertical,
            "coverage": coverage,
            "rating": rating,
            "saved": saved,
            "lenses": lenses(),
            "verticals": verticals(),
        },
    )


@app.get("/taste", response_class=HTMLResponse)
def taste_page(request: Request):
    profile, taste_source = load_taste()
    with session_scope() as session:
        rated = list(
            session.execute(
                select(QuestionRow, RatingRow.stars)
                .join(RatingRow, RatingRow.question_id == QuestionRow.id)
                .order_by(RatingRow.updated_at.desc())
            ).all()
        )
        pairs = []
        for q, stars in rated:
            session.expunge(q)
            pairs.append((q, stars))
        lens_avgs = session.execute(
            select(QuestionRow.lens, func.avg(RatingRow.stars), func.count())
            .join(RatingRow, RatingRow.question_id == QuestionRow.id)
            .group_by(QuestionRow.lens)
        ).all()
        dup_n = session.scalar(
            select(func.count()).where(QuestionRow.status == "duplicate")
        ) or 0
        curated_n = session.scalar(
            select(func.count()).where(QuestionRow.status == "curated")
        ) or 0
    return templates.TemplateResponse(
        request,
        "taste.html",
        {
            **_nav_ctx(request, "taste"),
            "profile": profile,
            "rated": pairs,
            "lens_avgs": lens_avgs,
            "lexical_duplicate_count": dup_n,
            "curated_count": curated_n,
            "taste_steering": steering_label(taste_source),
            "assets": load_assets(),
            "asset_headings": ASSET_HEADINGS,
        },
    )


@app.get("/opportunities", response_class=HTMLResponse)
def opportunities_page(request: Request, verdict: str = ""):
    with session_scope() as session:
        stmt = select(OpportunityRow).order_by(OpportunityRow.created_at.desc())
        rows = list(session.scalars(stmt))
        for row in rows:
            session.expunge(row)
    wanted = (verdict or "").strip().lower()
    if wanted == "none":
        rows = [r for r in rows if not r.latest_verdict]
    elif wanted in {"pursue", "park", "kill"}:
        rows = [r for r in rows if r.latest_verdict == wanted]
    return templates.TemplateResponse(
        request,
        "opportunities.html",
        {
            **_nav_ctx(request, "opportunities"),
            "opportunities": [_opportunity_view(r) for r in rows],
            "verdict": wanted,
        },
    )


@app.get("/issues", response_class=HTMLResponse)
def issues_index(request: Request):
    with session_scope() as session:
        rows = list(session.scalars(select(IssueRow).order_by(IssueRow.week_ending.desc())).all())
        for r in rows:
            session.expunge(r)
    return templates.TemplateResponse(
        request,
        "issues.html",
        {
            **_nav_ctx(request, "issues"),
            "issues": rows,
            "latest": rows[0] if rows else None,
            "gate_open": publish_gate_open(),
            "gate_reasons": gate_reasons(),
            "voice_ready": voice_is_filled(),
        },
    )


@app.get("/issues/{day}.md")
def download_issue(day: str):
    with session_scope() as session:
        row = session.scalar(select(IssueRow).where(IssueRow.week_ending == day))
        if not row:
            raise HTTPException(404, "No issue draft for that week")
        body = row.markdown
    return PlainTextResponse(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="correspondent-{day}.md"'},
    )


@app.get("/issues/{day}", response_class=HTMLResponse)
def issue_day(request: Request, day: str):
    with session_scope() as session:
        row = session.scalar(select(IssueRow).where(IssueRow.week_ending == day))
        if not row:
            raise HTTPException(404, "No issue draft for that week")
        session.expunge(row)
    return templates.TemplateResponse(
        request,
        "issue.html",
        {
            **_nav_ctx(request, "issues"),
            "issue": row,
            "gate_open": publish_gate_open(),
            "gate_reasons": gate_reasons(),
            "voice_ready": voice_is_filled(),
        },
    )


@app.get("/controls", response_class=HTMLResponse)
def controls(request: Request):
    with session_scope() as session:
        runs = list(
            session.scalars(select(RunRow).order_by(RunRow.started_at.desc()).limit(8)).all()
        )
        started_labels = {r.id: format_local(r.started_at) for r in runs}
        for r in runs:
            if r.error:
                r.error = public_run_error(r.error)
            session.expunge(r)
    lock = current_lock()
    active = _active_run()
    return templates.TemplateResponse(
        request,
        "controls.html",
        {
            **_nav_ctx(request, "controls"),
            "runs": runs,
            "started_labels": started_labels,
            "lock": lock,
            "verticals": verticals(),
            "lenses": lenses(),
            "settings": get_settings(),
            "run_control": {
                **run_control(),
                "stage_words": stage_words(active.current_stage) if active else "",
            },
            "run_failure_lines": {
                r.id: failure_lines_from_warnings(r.warnings) for r in runs
            },
        },
    )


def _digest_page(request: Request, row: DigestRow) -> HTMLResponse:
    row.markdown = public_page_text(row.markdown)
    if row.warnings:
        row.warnings = [public_warning(str(w)) for w in row.warnings]
    return templates.TemplateResponse(
        request,
        "digest.html",
        {**_nav_ctx(request, "archive"), "digest": row},
    )


def _digest_markdown(row: DigestRow, filename: str) -> PlainTextResponse:
    return PlainTextResponse(
        public_page_text(row.markdown),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/digest/run/{run_id}.md")
def download_digest_run(run_id: int):
    """One digest per run — a same-day second click must stay downloadable."""
    with session_scope() as session:
        row = session.scalar(select(DigestRow).where(DigestRow.run_id == run_id))
        if not row:
            raise HTTPException(404, "No digest for that run")
        session.expunge(row)
    return _digest_markdown(row, f"question-engine-run-{run_id}.md")


@app.get("/digest/run/{run_id}", response_class=HTMLResponse)
def digest_run(request: Request, run_id: int):
    with session_scope() as session:
        row = session.scalar(select(DigestRow).where(DigestRow.run_id == run_id))
        if not row:
            raise HTTPException(404, "No digest for that run")
        session.expunge(row)
    return _digest_page(request, row)


@app.get("/digest/{day}.md")
def download_digest(day: str):
    with session_scope() as session:
        row = session.scalar(
            select(DigestRow)
            .where(DigestRow.date == day)
            .order_by(DigestRow.created_at.desc(), DigestRow.id.desc())
        )
        if not row:
            raise HTTPException(404, "No digest for that date")
        body = public_page_text(row.markdown)
    filename = f"question-engine-{day}.md"
    return PlainTextResponse(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/digest/{day}", response_class=HTMLResponse)
def digest_day(request: Request, day: str):
    with session_scope() as session:
        row = session.scalar(
            select(DigestRow)
            .where(DigestRow.date == day)
            .order_by(DigestRow.created_at.desc(), DigestRow.id.desc())
        )
        if not row:
            raise HTTPException(404, "No digest for that date")
        session.expunge(row)
    return _digest_page(request, row)


class RatingIn(BaseModel):
    stars: int = Field(ge=1, le=5)
    why: str = ""


@app.post("/api/questions/{question_id}/rating")
def rate_question(question_id: str, body: RatingIn):
    with session_scope() as session:
        q = session.get(QuestionRow, question_id)
        if not q:
            raise HTTPException(404, "Unknown question")
        existing = session.scalar(
            select(RatingRow).where(RatingRow.question_id == question_id)
        )
        why = (body.why or "").strip()
        if existing:
            existing.stars = body.stars
            existing.updated_at = datetime.now(timezone.utc)
            if why:
                existing.why = why
        else:
            session.add(RatingRow(question_id=question_id, stars=body.stars, why=why))
    return {"ok": True, "stars": body.stars, "why": why}


@app.post("/api/questions/{question_id}/promote")
def promote_question(question_id: str):
    with session_scope() as session:
        q = session.get(QuestionRow, question_id)
        if not q:
            raise HTTPException(404, "Unknown question")
        q.promoted = True
        if q.promoted_at is None:
            q.promoted_at = datetime.now(timezone.utc)
        status = q.status
        rank = q.rank
        when = q.promoted_at
    return {
        "ok": True,
        "promoted": True,
        "status": status,
        "rank": rank,
        "promoted_at": when.isoformat() if when else None,
    }


class VerdictIn(BaseModel):
    verdict: str
    why: str = ""


class AssetsIn(BaseModel):
    businesses: str = ""
    reach: str = ""
    skills: str = ""
    capital_time: str = ""
    wont_do: str = ""


@app.post("/api/questions/{question_id}/assay")
def assay_question(question_id: str):
    from swarm.agents.desk import assays_today, run_desk
    from swarm.budget import RunBudget
    from swarm.llm import LLM

    settings = get_settings()
    if assays_today() >= settings.assays_per_day:
        raise HTTPException(
            429,
            f"ASSAYS_PER_DAY exceeded: {assays_today()} assays today (cap {settings.assays_per_day})",
        )
    with session_scope() as session:
        q = session.get(QuestionRow, question_id)
        if not q:
            raise HTTPException(404, "Unknown question")
        session.expunge(q)
        briefs = list(session.query(BriefRow).filter(BriefRow.run_id == q.run_id))
        for brief in briefs:
            session.expunge(brief)
    llm = LLM(RunBudget(settings.run_budget_usd))
    llm.run_id = q.run_id
    llm.agent = "desk"
    warnings: list[str] = []
    cards = run_desk(
        run_id=q.run_id,
        questions=[q],
        briefs=briefs,
        llm=llm,
        previous_started=None,
        warnings=warnings,
        on_demand=True,
    )
    if not cards:
        raise HTTPException(409, warnings[-1] if warnings else "Desk wrote no card")
    return {"ok": True, "opportunity_id": cards[0].get("id"), "warnings": warnings}


@app.post("/api/opportunities/{opportunity_id}/verdict")
def decide_opportunity(opportunity_id: str, body: VerdictIn):
    try:
        return apply_verdict(opportunity_id, body.verdict, body.why)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/assets")
def update_assets(body: AssetsIn):
    return {"ok": True, "assets": save_assets(body.model_dump())}


@app.post("/api/run")
def trigger_run(request: Request, force: bool = Query(False)):
    global _run_thread
    refuse_if_over_ceiling()
    refuse_if_cooling_down(request)
    if current_lock() is not None and not force:
        raise HTTPException(409, "A swarm run is already in progress")
    with _run_lock:
        if _run_thread and _run_thread.is_alive():
            raise HTTPException(409, "A swarm run is already in progress")

        def _target() -> None:
            from swarm.run_daily import main as swarm_main

            swarm_main(["--force"] if force else [])

        _run_thread = threading.Thread(target=_target, daemon=True)
        _run_thread.start()
    mark_accepted(request)
    return {"ok": True, "started": True}


@app.post("/api/issues")
def trigger_issue():
    """Draft this week's Correspondent issue. Never publishes."""
    global _issue_thread
    if current_lock(name="correspondent") is not None:
        raise HTTPException(409, "A Correspondent draft is already in progress")
    with _issue_lock:
        if _issue_thread and _issue_thread.is_alive():
            raise HTTPException(409, "A Correspondent draft is already in progress")

        def _target() -> None:
            from swarm.run_correspondent import main as issue_main

            issue_main(["--force"])

        _issue_thread = threading.Thread(target=_target, daemon=True)
        _issue_thread.start()
    return {"ok": True, "started": True, "published": False}


@app.get("/api/issues/status")
def issue_status():
    lock = current_lock(name="correspondent")
    with session_scope() as session:
        row = session.scalar(select(IssueRow).order_by(IssueRow.week_ending.desc()))
        latest = row.week_ending if row else None
    return {
        "running": lock is not None or (_issue_thread is not None and _issue_thread.is_alive()),
        "latest_issue": latest,
        "published": False,
    }


@app.get("/api/status")
def api_status():
    run = _active_run()
    digest = _latest_digest()
    return {
        "running": run is not None,
        "stage": run.current_stage if run else None,
        "stage_words": stage_words(run.current_stage) if run else None,
        "latest_digest": digest.date if digest else None,
    }
