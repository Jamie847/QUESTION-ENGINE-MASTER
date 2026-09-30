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
from swarm.display_time import age_days_from_finished, format_duration, format_run_stamp
from swarm.dedup import sample_near_miss_pairs
from swarm.lock import current_lock
from swarm.publish_gate import gate_reasons, publish_gate_open
from swarm.staleness import digest_age_days, is_stale, last_run_label
from swarm.models import Coverage, DecayClass, Question, QuestionStatus
from swarm.orm import (
    BriefRow,
    DigestRow,
    IntersectionRow,
    IssueRow,
    QuestionRow,
    RatingRow,
    RunRow,
)
from swarm.settings import get_settings
from dashboard.public_text import public_page_text, public_run_error, public_warning
from dashboard.run_limits import (
    mark_accepted,
    refuse_if_cooling_down,
    refuse_if_over_ceiling,
)
from swarm.sources.registry import missing_keys
from swarm.taste import load_taste, steering_label
from swarm.voice import voice_is_filled

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def _fmt_stamp(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return format_run_stamp(dt, get_settings().display_tz)


def _fmt_duration(started: datetime | None, finished: datetime | None) -> str:
    return format_duration(started, finished)


templates.env.globals["fmt_stamp"] = _fmt_stamp
templates.env.globals["fmt_duration"] = _fmt_duration
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
    spend = path in _SPEND_PATHS and request.method == "POST"

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
        provenance=getattr(row, "provenance", "") or "pre-wo006",
        written_by=getattr(row, "written_by", "") or "",
    )


def _decorate_questions(session, questions: list[QuestionRow]) -> dict[str, BriefRow]:
    ids: list[str] = []
    for question in questions:
        ids.extend(list(question.brief_ids or []))
    briefs: dict[str, BriefRow] = {}
    if ids:
        for brief in session.scalars(select(BriefRow).where(BriefRow.id.in_(ids))).all():
            briefs[brief.id] = brief
    for question in questions:
        provenance = getattr(question, "provenance", None) or "pre-wo006"
        question.provenance = provenance
        if provenance in {"unlinked", "pre-wo006"}:
            question.from_line = "sources not recorded"
            question.from_links = []
            continue
        links = []
        for brief_id in list(question.brief_ids or [])[:3]:
            brief = briefs.get(brief_id)
            if not brief:
                continue
            sources = list(brief.sources or [])
            names = list(brief.raw_signals or [])
            links.append(
                {
                    "headline": brief.headline,
                    "url": sources[0] if sources else "",
                    "source": names[0] if names else "",
                }
            )
        question.from_line = ""
        question.from_links = links
    return briefs


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


def _nav_ctx(request: Request, page: str) -> dict:
    return {
        "request": request,
        "page": page,
        "active_run": _active_run(),
    }


@app.get("/", response_class=HTMLResponse)
def today(request: Request):
    digest = _latest_digest()
    questions: list[QuestionRow] = []
    ratings: dict[str, int] = {}
    intersections: list[IntersectionRow] = []
    brief_rows: list[BriefRow] = []
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
            intersections = list(
                session.scalars(
                    select(IntersectionRow).where(IntersectionRow.run_id == digest.run_id)
                ).all()
            )
            brief_rows = list(
                session.scalars(select(BriefRow).where(BriefRow.run_id == digest.run_id)).all()
            )
            _decorate_questions(session, questions)
            if run:
                session.expunge(run)
            for q in questions:
                session.expunge(q)
            for i in intersections:
                session.expunge(i)
            for b in brief_rows:
                session.expunge(b)
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
    near_miss = sample_near_miss_pairs(
        [_question_from_row(q) for q in curated],
        prior_curated,
    )
    settings = get_settings()
    if run and run.finished_at:
        age_days = age_days_from_finished(run.finished_at, settings.display_tz)
    else:
        age_days = digest_age_days(digest.date) if digest else None
    briefs_by_vertical: dict[str, list] = {}
    for brief in brief_rows:
        briefs_by_vertical.setdefault(brief.vertical, []).append(brief)
    ran_verticals = sorted(briefs_by_vertical)
    ran_lenses = sorted({q.lens for q in questions})
    bank_groups = []
    for vertical in verticals():
        items = [q for q in bank if vertical["id"] in (q.verticals or [])]
        if items:
            bank_groups.append(
                {"id": vertical["id"], "name": vertical["name"], "questions": items}
            )
    if digest and digest.warnings:
        digest.warnings = [public_warning(str(w)) for w in digest.warnings]
    return templates.TemplateResponse(
        request,
        "today.html",
        {
            **_nav_ctx(request, "today"),
            "digest": digest,
            "run": run,
            "top": top,
            "bank": bank,
            "killed": killed[:6],
            "accepted": accepted,
            "rejected": rejected,
            "ratings": ratings,
            "duplicate_count": len(duplicates),
            "question_count": len(questions),
            "near_miss": near_miss,
            "has_prior_day": bool(prior_curated),
            "last_run_label": last_run_label(age_days) if age_days is not None else None,
            "digest_stale": is_stale(age_days, settings.stale_after_days)
            if age_days is not None
            else False,
            "stale_after_days": settings.stale_after_days,
            "briefs_by_vertical": briefs_by_vertical,
            "read_line": _read_line(run),
            "ran_verticals": ran_verticals,
            "ran_lenses": ran_lenses,
            "steering": steering_label(),
            "verticals": verticals(),
            "bank_groups": bank_groups,
        },
    )


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
        if saved == "1":
            stmt = select(QuestionRow).where(QuestionRow.promoted.is_(True))
            rows = list(
                session.scalars(stmt.order_by(QuestionRow.promoted_at.desc())).all()
            )
        else:
            stmt = select(QuestionRow).where(QuestionRow.status == "curated")
            if q:
                stmt = stmt.where(QuestionRow.text.ilike(f"%{q}%"))
            if lens:
                stmt = stmt.where(QuestionRow.lens == lens)
            if coverage:
                stmt = stmt.where(QuestionRow.coverage == coverage)
            rows = list(session.scalars(stmt.order_by(QuestionRow.created_at.desc())).all())
            if vertical:
                rows = [r for r in rows if vertical in (r.verticals or [])]
        rating_map = {
            r.question_id: r.stars
            for r in session.scalars(select(RatingRow)).all()
        }
        if rating.isdigit() and saved != "1":
            want = int(rating)
            rows = [r for r in rows if rating_map.get(r.id) == want]
        _decorate_questions(session, rows)
        run_ids = {r.run_id for r in rows}
        run_rows = []
        if run_ids:
            run_rows = list(
                session.scalars(select(RunRow).where(RunRow.id.in_(run_ids))).all()
            )
        digests = list(
            session.scalars(
                select(DigestRow).order_by(
                    DigestRow.date.desc(), DigestRow.created_at.desc()
                )
            ).all()
        )
        for r in rows:
            session.expunge(r)
        for d in digests:
            session.expunge(d)
        for run in run_rows:
            session.expunge(run)
    return templates.TemplateResponse(
        request,
        "archive.html",
        {
            **_nav_ctx(request, "archive"),
            "questions": rows,
            "digests": digests,
            "ratings": rating_map,
            "q": q,
            "lens": lens,
            "vertical": vertical,
            "coverage": coverage,
            "rating": rating,
            "lenses": lenses(),
            "verticals": verticals(),
            "saved": saved,
            "run_dates": {r.id: r.started_at for r in run_rows},
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
            "steering": steering_label(taste_source),
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
        for r in runs:
            if r.error:
                r.error = public_run_error(r.error)
            session.expunge(r)
    lock = current_lock()
    return templates.TemplateResponse(
        request,
        "controls.html",
        {
            **_nav_ctx(request, "controls"),
            "runs": runs,
            "lock": lock,
            "verticals": verticals(),
            "lenses": lenses(),
            "settings": get_settings(),
            "missing_keys": missing_keys(),
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
    why: str | None = None


@app.post("/api/questions/{question_id}/rating")
def rate_question(question_id: str, body: RatingIn):
    with session_scope() as session:
        q = session.get(QuestionRow, question_id)
        if not q:
            raise HTTPException(404, "Unknown question")
        existing = session.scalar(
            select(RatingRow).where(RatingRow.question_id == question_id)
        )
        if existing:
            existing.stars = body.stars
            if body.why is not None:
                existing.why = body.why.strip()
            existing.updated_at = datetime.now(timezone.utc)
        else:
            session.add(
                RatingRow(
                    question_id=question_id,
                    stars=body.stars,
                    why=(body.why or "").strip(),
                )
            )
    return {"ok": True, "stars": body.stars}


@app.post("/api/questions/{question_id}/promote")
def promote_question(question_id: str):
    with session_scope() as session:
        q = session.get(QuestionRow, question_id)
        if not q:
            raise HTTPException(404, "Unknown question")
        q.promoted = True
        q.promoted_at = datetime.now(timezone.utc)
    return {"ok": True, "status": q.status}


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
        "latest_digest": digest.date if digest else None,
    }
