"""Collect, embed, search. The catalog can be dropped and rebuilt."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, text

from swarm.db import get_engine, session_scope
from swarm.memory.embed import cosine, embed_texts
from swarm.settings import get_settings
from swarm.orm import (
    BriefRow,
    DigestRow,
    IntersectionRow,
    MemoryItemRow,
    OpportunityRow,
    OpportunityVerdictRow,
    QuestionRow,
    RunRow,
)

log = logging.getLogger("swarm.memory")

MEMORY_NOT_UPDATED = "memory not updated"
KINDS = ("question", "brief", "intersection", "opportunity", "verdict")


def _item_id(kind: str, ref_id: str) -> str:
    return f"{kind}:{ref_id}"


def _current_model() -> tuple[str, int]:
    settings = get_settings()
    return settings.embed_model, int(settings.embed_dims)


def _href_for(row: MemoryItemRow) -> str:
    if row.kind == "opportunity":
        return f"/opportunities#opp-{row.ref_id}"
    if row.kind == "verdict":
        return f"/opportunities#opp-{row.ref_id.split(':', 1)[0]}" if ":" in row.ref_id else f"/digest/run/{row.run_id}"
    if row.kind == "question":
        return f"/?q={row.ref_id}#{row.ref_id}"
    return f"/digest/run/{row.run_id}"


def _sync_pgvector(item_id: str, embedding: list[float]) -> None:
    engine = get_engine()
    if engine.dialect.name != "postgresql" or not embedding:
        return
    literal = "[" + ",".join(f"{float(x):.8f}" for x in embedding) + "]"
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE memory_items SET embedding_vec = CAST(:lit AS vector) "
                    "WHERE id = :id"
                ),
                {"lit": literal, "id": item_id},
            )
    except Exception as exc:  # noqa: BLE001 — catalog JSON is enough to search
        log.warning("embedding_vec sync failed id=%s %s", item_id, exc)


def index_item(
    *,
    kind: str,
    ref_id: str,
    text: str,
    run_id: int,
    item_date: str,
    title: str = "",
    verticals: list[str] | None = None,
    source_urls: list[str] | None = None,
    verdict: str = "",
    verdict_why: str = "",
    embed_model: str | None = None,
    embed_dims: int | None = None,
    embedding: list[float] | None = None,
) -> str:
    model, dims = _current_model()
    embed_model = embed_model or model
    embed_dims = embed_dims if embed_dims is not None else dims
    vector = embedding
    if vector is None:
        vector = embed_texts([text], input_type="document", model=embed_model, dims=embed_dims)[0]
    mid = _item_id(kind, ref_id)
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        row = session.get(MemoryItemRow, mid)
        if row is None:
            row = MemoryItemRow(id=mid, kind=kind, ref_id=ref_id)
            session.add(row)
        row.text = text
        row.title = title
        row.run_id = run_id
        row.item_date = item_date
        row.verticals = list(verticals or [])
        row.source_urls = list(source_urls or [])
        row.embedding = list(vector)
        row.embed_model = embed_model
        row.embed_dims = int(embed_dims)
        row.verdict = verdict
        row.verdict_why = verdict_why
        row.embedded_at = now
    _sync_pgvector(mid, list(vector))
    return mid


def _run_dates() -> dict[int, str]:
    dates: dict[int, str] = {}
    with session_scope() as session:
        for digest in session.scalars(select(DigestRow)).all():
            dates[digest.run_id] = digest.date
        for run in session.scalars(select(RunRow)).all():
            if run.id in dates:
                continue
            started = run.started_at
            if started is not None:
                dates[run.id] = started.date().isoformat()
    return dates


def collect_candidates(run_id: int | None = None) -> list[dict[str, Any]]:
    """Raw rows that belong in the catalog. Curated questions; not killed/dupes."""
    dates = _run_dates()
    out: list[dict[str, Any]] = []
    with session_scope() as session:
        q_stmt = select(QuestionRow).where(QuestionRow.status == "curated")
        b_stmt = select(BriefRow)
        i_stmt = select(IntersectionRow)
        o_stmt = select(OpportunityRow).where(OpportunityRow.status == "completed")
        v_stmt = select(OpportunityVerdictRow)
        if run_id is not None:
            q_stmt = q_stmt.where(QuestionRow.run_id == run_id)
            b_stmt = b_stmt.where(BriefRow.run_id == run_id)
            i_stmt = i_stmt.where(IntersectionRow.run_id == run_id)
            o_stmt = o_stmt.where(OpportunityRow.run_id == run_id)
        questions = list(session.scalars(q_stmt).all())
        briefs = list(session.scalars(b_stmt).all())
        intersections = list(session.scalars(i_stmt).all())
        opps = list(session.scalars(o_stmt).all())
        verdicts = list(session.scalars(v_stmt).all())
        briefs_by_id = {b.id: b for b in session.scalars(select(BriefRow)).all()}
        q_by_id = {q.id: q for q in session.scalars(select(QuestionRow)).all()}
        opp_by_id = {o.id: o for o in session.scalars(select(OpportunityRow)).all()}

        for q in questions:
            out.append(
                {
                    "kind": "question",
                    "ref_id": q.id,
                    "text": f"{q.title or ''} {q.text or ''}".strip(),
                    "title": q.title or (q.text or "")[:80],
                    "run_id": q.run_id,
                    "item_date": dates.get(q.run_id, ""),
                    "verticals": list(q.verticals or []),
                    "source_urls": [
                        u
                        for bid in (q.brief_ids or [])
                        for u in (getattr(briefs_by_id.get(bid), "sources", None) or [])
                        if u
                    ],
                }
            )
        for b in briefs:
            out.append(
                {
                    "kind": "brief",
                    "ref_id": b.id,
                    "text": f"{b.headline or ''} {b.what_is_happening or ''}".strip(),
                    "title": b.headline or "",
                    "run_id": b.run_id,
                    "item_date": dates.get(b.run_id, ""),
                    "verticals": [b.vertical] if b.vertical else [],
                    "source_urls": list(b.sources or []),
                }
            )
        for row in intersections:
            out.append(
                {
                    "kind": "intersection",
                    "ref_id": row.id,
                    "text": row.thesis or "",
                    "title": (row.thesis or "")[:80],
                    "run_id": row.run_id,
                    "item_date": dates.get(row.run_id, ""),
                    "verticals": list(row.verticals or []),
                    "source_urls": [],
                }
            )
        for row in opps:
            q = q_by_id.get(row.question_id)
            title = (q.title or q.text[:80]) if q else row.who_has_problem or row.id
            shape = row.picked_shape or ""
            out.append(
                {
                    "kind": "opportunity",
                    "ref_id": row.id,
                    "text": f"{title} {row.whats_actually_true or ''} {shape}".strip(),
                    "title": title,
                    "run_id": row.run_id,
                    "item_date": dates.get(row.run_id, ""),
                    "verticals": list(q.verticals or []) if q else [],
                    "source_urls": [],
                    "verdict": row.latest_verdict or "",
                    "verdict_why": row.latest_verdict_why or "",
                }
            )
        for row in verdicts:
            opp = opp_by_id.get(row.opportunity_id)
            if run_id is not None and (opp is None or opp.run_id != run_id):
                continue
            q = q_by_id.get(opp.question_id) if opp else None
            title = (q.title or q.text[:80]) if q else (opp.who_has_problem if opp else row.opportunity_id)
            out.append(
                {
                    "kind": "verdict",
                    "ref_id": f"{row.opportunity_id}:{row.id}",
                    "text": f"{row.verdict} {row.why or ''} {title}".strip(),
                    "title": title,
                    "run_id": opp.run_id if opp else 0,
                    "item_date": dates.get(opp.run_id, "") if opp else "",
                    "verticals": list(q.verticals or []) if q else [],
                    "source_urls": [],
                    "verdict": row.verdict,
                    "verdict_why": row.why or "",
                }
            )
    return [row for row in out if row.get("text")]


def _indexed_keys(model: str, dims: int) -> set[tuple[str, str]]:
    with session_scope() as session:
        rows = session.scalars(
            select(MemoryItemRow).where(
                MemoryItemRow.embed_model == model,
                MemoryItemRow.embed_dims == dims,
            )
        ).all()
        return {(r.kind, r.ref_id) for r in rows}


def pending_items(run_id: int | None = None) -> list[dict[str, Any]]:
    model, dims = _current_model()
    have = _indexed_keys(model, dims)
    return [
        row
        for row in collect_candidates(run_id)
        if (row["kind"], row["ref_id"]) not in have
    ]


def pending_ref_ids(run_id: int | None = None) -> set[str]:
    return {row["ref_id"] for row in pending_items(run_id)}


def _embed_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    if not rows:
        return {"embedded": 0, "ok": True}
    model, dims = _current_model()
    texts = [row["text"] for row in rows]
    vectors = embed_texts(texts, input_type="document", model=model, dims=dims)
    n = 0
    for row, vector in zip(rows, vectors, strict=True):
        index_item(
            kind=row["kind"],
            ref_id=row["ref_id"],
            text=row["text"],
            run_id=int(row["run_id"] or 0),
            item_date=row.get("item_date") or "",
            title=row.get("title") or "",
            verticals=list(row.get("verticals") or []),
            source_urls=list(row.get("source_urls") or []),
            verdict=row.get("verdict") or "",
            verdict_why=row.get("verdict_why") or "",
            embed_model=model,
            embed_dims=dims,
            embedding=list(vector),
        )
        n += 1
    return {"embedded": n, "ok": True}


def embed_run(run_id: int) -> dict[str, Any]:
    try:
        return {**_embed_rows(pending_items(run_id)), "run_id": run_id}
    except Exception as exc:
        log.warning("embed_run failed run=%s %s", run_id, exc)
        return {"embedded": 0, "ok": False, "run_id": run_id, "error": str(exc)}


def embed_all_pending() -> dict[str, Any]:
    try:
        return _embed_rows(pending_items())
    except Exception as exc:
        log.warning("embed_all_pending failed %s", exc)
        return {"embedded": 0, "ok": False, "error": str(exc)}


def rebuild_memory() -> dict[str, Any]:
    """Drop the catalog and re-embed. Raw tables are not touched."""
    with session_scope() as session:
        session.execute(delete(MemoryItemRow))
    result = embed_all_pending()
    return {"embedded": int(result.get("embedded") or 0), "ok": bool(result.get("ok"))}


def remember_after_archive(run_id: int, warnings: list[str]) -> None:
    """Optional stage. Voyage errors never block a digest."""
    try:
        result = embed_run(run_id)
        if result.get("ok"):
            return
    except Exception as exc:  # noqa: BLE001
        log.warning("memory after archive failed run=%s %s", run_id, exc)
        result = {"ok": False}
    if MEMORY_NOT_UPDATED not in warnings:
        warnings.append(MEMORY_NOT_UPDATED)
    _stamp_digest(run_id)


def _stamp_digest(run_id: int) -> None:
    with session_scope() as session:
        digest = session.scalar(
            select(DigestRow)
            .where(DigestRow.run_id == run_id)
            .order_by(DigestRow.id.desc())
        )
        if digest is None:
            return
        warns = list(digest.warnings or [])
        if MEMORY_NOT_UPDATED not in warns:
            warns.append(MEMORY_NOT_UPDATED)
        digest.warnings = warns
        body = digest.markdown or ""
        if MEMORY_NOT_UPDATED not in body:
            digest.markdown = body.rstrip() + f"\n\n_{MEMORY_NOT_UPDATED}._\n"
        run = session.get(RunRow, run_id)
        if run is not None:
            run_warns = list(run.warnings or [])
            if MEMORY_NOT_UPDATED not in run_warns:
                run_warns.append(MEMORY_NOT_UPDATED)
            run.warnings = run_warns


def _exact_boost(query: str, text: str) -> float:
    q = (query or "").strip()
    blob = text or ""
    if not q:
        return 0.0
    if q.lower() in blob.lower():
        return 2.0
    q_tokens = {t for t in q.lower().replace(".", " ").split() if len(t) > 1}
    b_tokens = {t for t in blob.lower().replace(".", " ").split() if len(t) > 1}
    if not q_tokens:
        return 0.0
    return 0.5 * (len(q_tokens & b_tokens) / len(q_tokens))


def _as_result(row: MemoryItemRow, score: float) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "ref_id": row.ref_id,
        "title": row.title,
        "text": row.text,
        "item_date": row.item_date,
        "run_id": row.run_id,
        "verdict": row.verdict,
        "verdict_why": row.verdict_why,
        "verticals": list(row.verticals or []),
        "href": _href_for(row),
        "score": round(score, 4),
    }


def search_memory(
    query: str,
    *,
    kind: str = "",
    vertical: str = "",
    newest: bool = False,
    kinds: list[str] | None = None,
    exclude_run: int | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    q = (query or "").strip()
    model, dims = _current_model()
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(MemoryItemRow).where(
                    MemoryItemRow.embed_model == model,
                    MemoryItemRow.embed_dims == dims,
                )
            ).all()
        )
        for row in rows:
            session.expunge(row)
    if kinds:
        allowed = set(kinds)
        rows = [r for r in rows if r.kind in allowed]
    if kind:
        rows = [r for r in rows if r.kind == kind]
    if vertical:
        rows = [r for r in rows if vertical in (r.verticals or [])]
    if exclude_run is not None:
        rows = [r for r in rows if r.run_id != exclude_run]
    if not rows:
        return {"results": [], "query": q}
    qvec: list[float] = []
    if q:
        try:
            qvec = embed_texts([q], input_type="query", model=model, dims=dims)[0]
        except Exception as exc:
            log.warning("query embed failed %s", exc)
            qvec = []
    scored: list[tuple[float, MemoryItemRow]] = []
    for row in rows:
        vec = [float(x) for x in (row.embedding or [])]
        meaning = cosine(qvec, vec) if qvec else 0.0
        score = meaning + _exact_boost(q, f"{row.title} {row.text}")
        scored.append((score, row))
    if newest:
        scored.sort(key=lambda pair: (pair[1].item_date, pair[0]), reverse=True)
    else:
        scored.sort(key=lambda pair: pair[0], reverse=True)
    results = [_as_result(row, score) for score, row in scored[:limit] if score > 0 or not q]
    if not q:
        results = [_as_result(row, score) for score, row in scored[:limit]]
    return {"results": results, "query": q}


# silence unused import if KINDS is referenced only by callers
_ = KINDS
