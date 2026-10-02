"""Opportunity desk. Assay, shape, prove on paper. Never contacts anyone."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from swarm.config import business_shapes
from swarm.db import session_scope
from swarm.desk.assets import load_assets
from swarm.desk.select import select_for_desk
from swarm.memory.recall import format_for_prompt, recall_for_desk
from swarm.desk.validate import (
    apply_number_rule,
    evidence_blob,
    filter_prospects,
    fit_from_assets,
    rivals_phrase,
)
from swarm.llm import LLM
from swarm.orm import OpportunityRow, QuestionRow, RunRow
from swarm.settings import get_settings

log = logging.getLogger("swarm.desk")

ROOT = Path(__file__).resolve().parent.parent
CHECK_NOTE = (
    "Checked from stored snippets and search snippets — cited pages were not fetched."
)
CLAIMS_PROMPT = (ROOT / "prompts" / "desk_claims.md").read_text(encoding="utf-8")
CARD_PROMPT = (ROOT / "prompts" / "desk_card.md").read_text(encoding="utf-8")

CLAIMS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "claim": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                },
                "required": ["claim"],
            },
        }
    },
    "required": ["claims"],
}

CARD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "claim": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": [
                            "supported",
                            "partly supported",
                            "contradicted",
                            "unverified",
                        ],
                    },
                    "links": {"type": "array", "items": {"type": "string"}},
                    "correction": {"type": "string"},
                },
                "required": ["claim", "verdict"],
            },
        },
        "whats_actually_true": {"type": "string"},
        "shapes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "kind": {"type": "string"},
                    "line": {"type": "string"},
                    "picked": {"type": "boolean"},
                },
                "required": ["kind", "line"],
            },
        },
        "who_has_problem": {"type": "string"},
        "who_pays": {"type": "string"},
        "what_they_use_today": {"type": "string"},
        "why_now": {"type": "string"},
        "how_it_charges": {"type": "string"},
        "rivals": {"type": "array", "items": {"type": "string"}},
        "first_prospects": {"type": "array", "items": {"type": "string"}},
        "fit": {"type": "string"},
        "weekend_test": {"type": "string"},
        "why_it_might_fail": {"type": "string"},
        "red_flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["whats_actually_true", "who_has_problem"],
}

SearchFn = Callable[[str], list[dict[str, Any]]]


def _allowed_shapes() -> set[str]:
    return {name.lower() for name in business_shapes()}


def _brief_bundle(question: Any, briefs: list[Any]) -> list[Any]:
    ids = set(getattr(question, "brief_ids", None) or [])
    if not ids:
        return list(briefs)
    return [b for b in briefs if getattr(b, "id", "") in ids]


def name_claims(*, question: Any, briefs: list[Any], llm: LLM) -> list[dict[str, Any]]:
    related = _brief_bundle(question, briefs)
    lines = [
        f"Question: {getattr(question, 'title', '')}",
        getattr(question, "text", ""),
        "",
        "Stored snippets:",
    ]
    for brief in related:
        lines.append(f"- {getattr(brief, 'headline', '')}")
        lines.append(f"  {getattr(brief, 'what_is_happening', '')}")
        lines.append(f"  {getattr(brief, 'why_now', '')}")
        for url in getattr(brief, "sources", None) or []:
            lines.append(f"  {url}")
    data = llm.complete_json(
        system=CLAIMS_PROMPT,
        user="\n".join(lines),
        schema=CLAIMS_SCHEMA,
        max_tokens=2000,
        judgment=True,
        reserve=True,
        estimate_in=2500,
        estimate_out=800,
    )
    if not data:
        return []
    rows = [r for r in (data.get("claims") or []) if isinstance(r, dict) and r.get("claim")]
    return rows[:3]


def _wordings(claim: str) -> list[str]:
    text = " ".join(str(claim).split())
    return [text, f"evidence that this is not true: {text}"]


def collect_searches(claims: list[dict[str, Any]], search_fn: SearchFn) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for row in claims:
        for query in _wordings(row.get("claim") or ""):
            try:
                found = search_fn(query) or []
            except Exception as exc:  # noqa: BLE001 — desk continues on a dark search
                log.warning("desk search failed q=%s %s", query, exc)
                found = []
            for item in found[:5]:
                hits.append(
                    {
                        "query": query,
                        "title": str(item.get("title") or ""),
                        "url": str(item.get("url") or ""),
                        "snippet": str(item.get("snippet") or ""),
                    }
                )
            if not found:
                hits.append({"query": query, "title": "", "url": "", "snippet": ""})
    return hits


def _card_user(
    question: Any,
    briefs: list[Any],
    claims: list[dict[str, Any]],
    searches: list[dict[str, Any]],
    assets: dict[str, str],
    related_memory: list[dict[str, Any]] | None = None,
) -> str:
    lines = [
        f"Question: {getattr(question, 'title', '')}",
        getattr(question, "text", ""),
        "",
        "Claims named earlier:",
    ]
    for row in claims:
        lines.append(f"- {row.get('claim')}")
    lines.append("")
    lines.append("Stored snippets:")
    for brief in briefs:
        lines.append(f"- {getattr(brief, 'headline', '')}: {getattr(brief, 'what_is_happening', '')}")
        lines.append(f"  {getattr(brief, 'why_now', '')}")
        for url in getattr(brief, "sources", None) or []:
            lines.append(f"  {url}")
    lines.append("")
    lines.append("Search snippets:")
    for hit in searches:
        if not (hit.get("title") or hit.get("snippet")):
            lines.append(f"- query {hit.get('query')}: no results")
            continue
        lines.append(f"- {hit.get('title')} ({hit.get('url')})")
        lines.append(f"  {hit.get('snippet')}")
    lines.append("")
    lines.append("Allowed shapes: " + ", ".join(business_shapes()))
    lines.append("Assets profile:")
    if any(str(v).strip() for v in (assets or {}).values()):
        for key, val in assets.items():
            if str(val).strip():
                lines.append(f"- {key}: {val}")
    else:
        lines.append("(empty — leave fit blank)")
    lines.append("")
    lines.append(format_for_prompt(related_memory or []))
    return "\n".join(lines)


def write_card(
    *,
    question: Any,
    briefs: list[Any],
    claims: list[dict[str, Any]],
    searches: list[dict[str, Any]],
    assets: dict[str, str],
    llm: LLM,
    related_memory: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    return llm.complete_json(
        system=CARD_PROMPT,
        user=_card_user(
            question, briefs, claims, searches, assets, related_memory
        ),
        schema=CARD_SCHEMA,
        max_tokens=4000,
        judgment=True,
        reserve=True,
        estimate_in=3500,
        estimate_out=1500,
    )


def run_one_opportunity(
    *,
    question: Any,
    briefs: list[Any],
    claims: list[dict[str, Any]],
    card: dict[str, Any],
    searches: list[dict[str, Any]],
    assets: dict[str, str],
    n_searches: int,
) -> dict[str, Any]:
    related = _brief_bundle(question, briefs)
    evidence = evidence_blob(related, searches)
    verdicts = [r for r in (card.get("claims") or claims) if isinstance(r, dict)]
    if not verdicts:
        verdicts = list(claims)
    all_unverified = bool(verdicts) and all(
        str(r.get("verdict") or "") == "unverified" for r in verdicts
    )
    if all_unverified:
        return {
            "status": "could_not_check",
            "claims": verdicts,
            "whats_actually_true": "could not check",
            "shapes": [],
            "picked_shape": "",
            "who_has_problem": "",
            "who_pays": "",
            "what_they_use_today": "",
            "why_now": "",
            "how_it_charges": "",
            "rivals": "",
            "first_prospects": [],
            "fit": fit_from_assets(assets) or "assets profile not written",
            "weekend_test": "",
            "why_it_might_fail": "",
            "red_flags": [],
            "check_note": CHECK_NOTE,
            "searches": searches,
        }

    allowed = _allowed_shapes()
    shapes = []
    for raw in card.get("shapes") or []:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "").strip()
        if kind.lower() not in allowed:
            continue
        shapes.append(
            {
                "kind": kind,
                "line": str(raw.get("line") or "").strip(),
                "picked": bool(raw.get("picked")),
            }
        )
    shapes = shapes[:3]
    if shapes and not any(s.get("picked") for s in shapes):
        shapes[0]["picked"] = True
    picked = next((s["kind"] for s in shapes if s.get("picked")), "")

    draft = {
        "whats_actually_true": str(card.get("whats_actually_true") or ""),
        "who_has_problem": str(card.get("who_has_problem") or ""),
        "who_pays": str(card.get("who_pays") or ""),
        "what_they_use_today": str(card.get("what_they_use_today") or "unknown"),
        "why_now": str(card.get("why_now") or ""),
        "how_it_charges": str(card.get("how_it_charges") or ""),
        "weekend_test": str(card.get("weekend_test") or ""),
        "why_it_might_fail": str(card.get("why_it_might_fail") or ""),
        "fit": str(card.get("fit") or ""),
        "rivals": rivals_phrase(
            [str(x) for x in (card.get("rivals") or [])], n_searches
        ),
    }
    cleaned, dirty = apply_number_rule(draft, evidence)
    if dirty:
        cleaned, _again = apply_number_rule(cleaned, evidence, second_pass=True)
    fit = fit_from_assets(assets) or cleaned.get("fit") or "assets profile not written"
    prospects = filter_prospects(
        [str(x) for x in (card.get("first_prospects") or [])], evidence
    )
    return {
        "status": "completed",
        "claims": verdicts,
        "whats_actually_true": cleaned.get("whats_actually_true") or "not available",
        "shapes": shapes,
        "picked_shape": picked,
        "who_has_problem": cleaned.get("who_has_problem") or "",
        "who_pays": cleaned.get("who_pays") or "",
        "what_they_use_today": cleaned.get("what_they_use_today") or "unknown",
        "why_now": cleaned.get("why_now") or "",
        "how_it_charges": cleaned.get("how_it_charges") or "",
        "rivals": cleaned.get("rivals") or rivals_phrase([], n_searches),
        "first_prospects": prospects,
        "fit": fit,
        "weekend_test": cleaned.get("weekend_test") or "",
        "why_it_might_fail": cleaned.get("why_it_might_fail") or "",
        "red_flags": [str(x) for x in (card.get("red_flags") or []) if str(x).strip()],
        "check_note": CHECK_NOTE,
        "searches": searches,
    }


def _opp_id(run_id: int, question_id: str) -> str:
    digest = hashlib.sha1(f"{run_id}:{question_id}".encode()).hexdigest()[:10]
    return f"r{run_id}-opp-{digest}"


def _persist(run_id: int, question_id: str, payload: dict[str, Any], *, on_demand: bool, cost: float, written_by: str) -> str:
    oid = _opp_id(run_id, question_id)
    with session_scope() as session:
        if session.get(RunRow, run_id) is None:
            return oid
        row = session.get(OpportunityRow, oid)
        if row is None:
            row = OpportunityRow(id=oid, run_id=run_id, question_id=question_id)
            session.add(row)
        row.status = payload.get("status") or "completed"
        row.skip_reason = payload.get("skip_reason") or ""
        row.claims = payload.get("claims") or []
        row.whats_actually_true = payload.get("whats_actually_true") or ""
        row.shapes = payload.get("shapes") or []
        row.picked_shape = payload.get("picked_shape") or ""
        row.who_has_problem = payload.get("who_has_problem") or ""
        row.who_pays = payload.get("who_pays") or ""
        row.what_they_use_today = payload.get("what_they_use_today") or ""
        row.why_now = payload.get("why_now") or ""
        row.how_it_charges = payload.get("how_it_charges") or ""
        row.rivals = payload.get("rivals") or ""
        row.first_prospects = payload.get("first_prospects") or []
        row.fit = payload.get("fit") or ""
        row.weekend_test = payload.get("weekend_test") or ""
        row.why_it_might_fail = payload.get("why_it_might_fail") or ""
        row.red_flags = payload.get("red_flags") or []
        row.check_note = payload.get("check_note") or CHECK_NOTE
        row.searches = payload.get("searches") or []
        row.related_from_memory = payload.get("related_from_memory") or []
        row.written_by = written_by
        row.cost_usd = cost
        row.on_demand = on_demand
    return oid


def _default_search(query: str) -> list[dict[str, Any]]:
    from swarm.sources.brave import search_web

    return search_web(query)


def run_desk(
    *,
    run_id: int,
    questions: list[Any],
    briefs: list[Any],
    llm: LLM,
    search_fn: SearchFn | None = None,
    assets: dict[str, str] | None = None,
    previous_started: datetime | None,
    warnings: list[str],
    on_demand: bool = False,
) -> list[dict[str, Any]]:
    settings = get_settings()
    if not llm.budget.can_spend(settings.desk_reserve_usd, reserve=True):
        warnings.append("Opportunity desk skipped — run budget spent.")
        return []
    extras = _saved_since(previous_started, exclude_run=run_id)
    picks, skipped = select_for_desk(
        list(questions) + extras,
        previous_started=previous_started,
        max_n=settings.opportunity_max,
    )
    if skipped:
        bits = ", ".join(f"{s.id} ({s.skip_reason})" for s in skipped[:8])
        warnings.append(f"Opportunity desk skipped unlinked or unverified: {bits}")
    if not picks:
        return []
    searcher = search_fn or _default_search
    profile = assets if assets is not None else load_assets()
    cards: list[dict[str, Any]] = []
    desk_cost = 0.0
    for row in picks:
        if not llm.budget.can_spend(settings.desk_reserve_usd, reserve=True):
            warnings.append("Opportunity desk stopped after budget — run budget spent.")
            break
        before = llm.budget.spent_usd
        started_agent = llm.agent
        llm.agent = "desk"
        related = _brief_bundle(row, briefs)
        if not related:
            related = list(briefs)
        named = name_claims(question=row, briefs=related, llm=llm)
        if not named:
            warnings.append(f"Opportunity desk could not name claims for {row.id}.")
            llm.agent = started_agent
            continue
        searches = collect_searches(named, searcher)
        n_searches = len({h.get("query") for h in searches if h.get("query")})
        memory = recall_for_desk(
            f"{getattr(row, 'title', '')} {getattr(row, 'text', '')}".strip(),
            run_id=run_id,
        )
        draft = write_card(
            question=row,
            briefs=related,
            claims=named,
            searches=searches,
            assets=profile,
            llm=llm,
            related_memory=memory,
        )
        llm.agent = started_agent
        if draft is None:
            warnings.append(f"Opportunity desk wrote no card for {row.id}.")
            continue
        built = run_one_opportunity(
            question=row,
            briefs=related,
            claims=named,
            card=draft,
            searches=searches,
            assets=profile,
            n_searches=n_searches or 2,
        )
        cost = max(0.0, llm.budget.spent_usd - before)
        built["cost_usd"] = cost
        built["related_from_memory"] = memory
        built["question_id"] = row.id
        built["id"] = _persist(
            run_id,
            row.id,
            built,
            on_demand=on_demand,
            cost=cost,
            written_by=llm.writer_name(judgment=True),
        )
        desk_cost += cost
        cards.append(built)
    if cards:
        warnings.append(
            f"Opportunity desk ${desk_cost:.2f} ({len(cards)} card"
            f"{'' if len(cards) == 1 else 's'})"
        )
    return cards


def _saved_since(previous_started: datetime | None, *, exclude_run: int) -> list[QuestionRow]:
    with session_scope() as session:
        rows = list(
            session.query(QuestionRow).filter(QuestionRow.promoted.is_(True)).all()
        )
        for row in rows:
            session.expunge(row)
    out = []
    for row in rows:
        if row.run_id == exclude_run:
            continue
        when = row.promoted_at
        if when is None:
            continue
        if previous_started is None or when >= previous_started:
            out.append(row)
    return out


def assays_today() -> int:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    with session_scope() as session:
        return (
            session.query(OpportunityRow)
            .filter(OpportunityRow.on_demand.is_(True))
            .filter(OpportunityRow.created_at >= start)
            .count()
        )
