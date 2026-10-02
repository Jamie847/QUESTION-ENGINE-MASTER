"""Re-resolve brief URLs from stored scout input. Never invent a neighbour."""

from __future__ import annotations

import json
import re
from typing import Any

from datetime import datetime, timezone

from swarm.agents.scout import urls_from_model
from swarm.db import session_scope
from swarm.models import Signal
from swarm.orm import AgentCallRow, BriefRow, DeployMarkerRow, QuestionRow
from swarm.primary import prefer_primary_urls

MARKER = "wo011_link_repair"

LABEL_BLOCK = re.compile(
    r"- (S\d+) \(([^,]+), rank \d+\) (.+?)\n(?:  .+\n)*?  (https?://\S+)",
    re.M,
)


def parse_scout_labels(input_text: str) -> dict[str, Signal] | None:
    if "Candidate signals:" not in (input_text or ""):
        return None
    labels: dict[str, Signal] = {}
    for match in LABEL_BLOCK.finditer(input_text):
        token, source, title, url = match.groups()
        labels[token] = Signal(
            source=source.strip(),
            title=title.strip() or url,
            url=url.strip(),
            snippet="",
            score=1.0,
        )
    return labels or None


def parse_scout_output(output_text: str) -> list[dict[str, Any]]:
    raw = (output_text or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return []
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return []
    if not isinstance(data, dict):
        return []
    return [row for row in (data.get("briefs") or []) if isinstance(row, dict)]


def resolve_brief_urls(raw: dict[str, Any], labels: dict[str, Signal]) -> list[str]:
    claimed = urls_from_model(raw, labels)
    text = " ".join(
        [
            str(raw.get("headline") or ""),
            str(raw.get("what_is_happening") or ""),
            str(raw.get("why_now") or ""),
        ]
    )
    return prefer_primary_urls(text, claimed, list(labels.values()))


def repair_already_ran() -> bool:
    with session_scope() as session:
        return session.get(DeployMarkerRow, MARKER) is not None


def _record_ran(detail: dict[str, int]) -> None:
    with session_scope() as session:
        row = session.get(DeployMarkerRow, MARKER)
        if row is None:
            session.add(
                DeployMarkerRow(
                    name=MARKER,
                    detail=detail,
                    ran_at=datetime.now(timezone.utc),
                )
            )
        else:
            row.detail = detail
            row.ran_at = datetime.now(timezone.utc)


def repair_past_links() -> dict[str, int]:
    """One-shot WO-011 re-resolve. A second call records skip and rewrites nothing."""
    empty = {"relinked": 0, "unverified": 0, "unlinked": 0, "skipped": 0}
    if repair_already_ran():
        return {**empty, "skipped": 1}
    relinked = 0
    unverified = 0
    unlinked = 0
    with session_scope() as session:
        calls = list(
            session.query(AgentCallRow)
            .filter(AgentCallRow.agent == "scout")
            .order_by(AgentCallRow.id)
        )
        if calls:
            run_ids = sorted({c.run_id for c in calls})
            briefs = list(session.query(BriefRow).filter(BriefRow.run_id.in_(run_ids)))
            questions = list(
                session.query(QuestionRow).filter(QuestionRow.run_id.in_(run_ids))
            )
            by_run: dict[int, list[BriefRow]] = {}
            for brief in briefs:
                by_run.setdefault(brief.run_id, []).append(brief)
            repaired_ids: set[str] = set()
            truncated_runs: set[int] = set()
            for call in calls:
                labels = parse_scout_labels(call.input_text or "")
                payloads = parse_scout_output(call.output_text or "")
                if labels is None or not payloads:
                    truncated_runs.add(call.run_id)
                    continue
                by_headline = {b.headline: b for b in by_run.get(call.run_id, [])}
                for raw in payloads:
                    headline = str(raw.get("headline") or "")
                    brief = by_headline.get(headline)
                    if brief is None:
                        continue
                    urls = resolve_brief_urls(raw, labels)
                    brief.sources = urls
                    repaired_ids.add(brief.id)
                    if urls:
                        relinked += 1
                    else:
                        unlinked += 1
            for brief in briefs:
                if brief.id in repaired_ids:
                    continue
                if brief.run_id in truncated_runs or brief.run_id in {
                    c.run_id for c in calls
                }:
                    brief.sources = []
            for question in questions:
                related = [
                    b
                    for b in by_run.get(question.run_id, [])
                    if b.id in (question.brief_ids or [])
                ]
                if question.run_id in truncated_runs and not any(
                    b.sources for b in related
                ):
                    question.provenance = "unverified"
                    unverified += 1
                elif any(b.sources for b in related):
                    question.provenance = "linked"
                else:
                    question.provenance = "unlinked"
                    if question.id:
                        unlinked += 1
    counts = {
        "relinked": relinked,
        "unverified": unverified,
        "unlinked": unlinked,
        "skipped": 0,
    }
    _record_ran(counts)
    return counts
