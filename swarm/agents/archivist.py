from __future__ import annotations

from datetime import date, datetime

from swarm.dedup import sample_near_miss_pairs
from swarm.display_time import age_days_from_finished, run_header
from swarm.settings import get_settings
from swarm.staleness import digest_age_days, is_stale, last_run_label
from swarm.taste import steering_label
from swarm.models import (
    Brief,
    DigestDoc,
    Intersection,
    Question,
    QuestionStatus,
    RunStatus,
    SourceHealth,
)


def render_digest(
    *,
    day: date,
    briefs: list[Brief],
    intersections: list[Intersection],
    questions: list[Question],
    health: list[SourceHealth],
    warnings: list[str],
    degraded: bool,
    cost_usd: float,
    prior_questions: list[Question] | None = None,
    as_of: date | None = None,
    run_id: int | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    status: str = "",
) -> DigestDoc:
    curated = sorted(
        [q for q in questions if q.status == QuestionStatus.curated],
        key=lambda q: q.rank or 99,
    )
    killed = [q for q in questions if q.status == QuestionStatus.killed]
    duplicates = [q for q in questions if q.status == QuestionStatus.duplicate]
    near_miss = sample_near_miss_pairs(questions, prior_questions or [])
    accepted = [i for i in intersections if i.accepted]
    rejected = [i for i in intersections if not i.accepted]
    top = curated[:5]
    model_n = sum(1 for q in questions if (q.written_by or "").startswith("model:"))
    lines: list[str] = [
        f"# Question Engine — {day.isoformat()}",
        "",
        f"_{model_n} of {len(questions)} questions model-written._",
        "",
    ]
    if run_id and started_at is not None:
        lines += [
            run_header(
                run_id=run_id,
                started_at=started_at,
                finished_at=finished_at,
                tz_name=get_settings().display_tz,
                cost_usd=cost_usd,
                status=status,
            ),
            "",
        ]
    if degraded:
        lines += [
            "> Degraded run. One or more sources or model calls failed; "
            "the digest is still complete from what survived.",
            "",
        ]
    lines += ["## Top questions", ""]
    if not top:
        lines += ["_No questions cleared the curator._", ""]
    for i, q in enumerate(top, start=1):
        lines += _question_block(i, q, briefs, intersections)

    lines += ["## Intersections of the day", ""]
    if not accepted:
        lines.append("_Cross-pollinator accepted nothing. See rejects below._")
        lines.append("")
    for inter in accepted:
        cov = inter.coverage.value
        lines.append(
            f"- **{' × '.join(inter.verticals)}** · surprise {inter.surprise:.2f} · "
            f"coverage **{cov}** (model guess) — {inter.thesis}"
        )
        if inter.coverage_notes:
            lines.append(f"  - coverage note: {inter.coverage_notes}")
    lines.append("")

    lines += ["## Full question bank", ""]
    by_v: dict[str, list[Question]] = {}
    for q in curated:
        key = " × ".join(q.verticals) if q.verticals else "uncategorized"
        by_v.setdefault(key, []).append(q)
    for key, qs in sorted(by_v.items()):
        lines.append(f"### {key}")
        for q in qs:
            flag = (
                f" · coverage (model guess) {q.coverage.value}"
                if q.coverage.value != "unknown"
                else ""
            )
            template = " · template" if q.written_by == "template" else ""
            lines.append(f"- {q.text} _{q.lens}{flag}{template}_")
        lines.append("")

    lines += ["## Cross-pollinator passed over", ""]
    if not rejected:
        lines.append("_No rejected intersections were logged._")
        lines.append("")
    for inter in rejected:
        reason = inter.reject_reason or "no reason given"
        lines.append(
            f"- **{' × '.join(inter.verticals)}** — {inter.thesis}  "
            f"_rejected: {reason}_"
        )
    lines.append("")

    lines += ["## Curator's kill floor (sample)", ""]
    sample = [q for q in killed if q.kill_reason][:6]
    if not sample:
        lines.append("_Nothing killed with a recorded reason._")
        lines.append("")
    for q in sample:
        lines.append(f"- {q.text}  _killed: {q.kill_reason}_")
    lines.append("")

    lines += ["## Near-miss review", ""]
    lines.append(
        "Dedup is **lexical** (content-token Jaccard). It does **not** catch "
        "paraphrase. A low duplicate count is not evidence that it works — only "
        "that it ran. Flag any pair below that means the same thing in different "
        "words. Three flagged pairs across keyed weeks is the re-trigger for a "
        "nullable vector column."
    )
    lines.append("")
    if not prior_questions:
        lines.append("_No prior digest. This section starts the next keyed day._")
        lines.append("")
    elif not near_miss:
        lines.append("_Prior digest has no surviving questions to pair._")
        lines.append("")
    else:
        for i, pair in enumerate(near_miss, start=1):
            share = (
                " × ".join(pair.shared_verticals)
                if pair.shared_verticals
                else "no shared vertical"
            )
            lines.append(f"### Pair {i} · lexical overlap {pair.score:.2f} · {share}")
            lines.append(f"- **Today:** {pair.today_text}")
            lines.append(f"- **Prior day:** {pair.prior_text}")
            lines.append("- _Same question in different words? If yes, flag it._")
            lines.append("")

    lines += ["## Source health", ""]
    for h in health:
        if h.dead:
            mark = "dead"
        elif h.ok:
            mark = "ok"
        else:
            mark = "DOWN"
        extra = f" — {h.error}" if h.error else ""
        skip = " (skipped)" if h.error == "skipped" else ""
        last = f", last ok {h.last_ok}" if h.last_ok and h.dead else ""
        lines.append(
            f"- {h.source}: {mark}, {h.count} signals, {h.elapsed_ms}ms{skip}{extra}{last}"
        )
    lines.append("")
    if warnings:
        lines += ["## Warnings", ""]
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")
    if finished_at is not None:
        age = age_days_from_finished(finished_at, get_settings().display_tz)
    else:
        age = digest_age_days(day, as_of=as_of)
    stale = is_stale(age, get_settings().stale_after_days)
    stale_note = " Digest is **stale**." if stale else ""
    lines.append(
        f"_{last_run_label(age).capitalize()}.{stale_note} "
        f"Runs are manual — there is no daily cron. "
        f"Run cost ≈ ${cost_usd:.2f}. Coverage is a model guess, never a search, "
        f"and is never used as promotion. "
        f"{steering_label()} "
        f"Lexical duplicates marked: {len(duplicates)} of {len(questions)}. "
        f"That number counts token overlap only; it does not catch paraphrase._"
    )
    lines.append("")

    markdown = "\n".join(lines)
    return DigestDoc(
        date=day.isoformat(),
        title=f"Question Engine — {day.isoformat()}",
        markdown=markdown,
        top_ids=[q.id for q in top],
        curated_count=len(curated),
        killed_count=len(killed),
        duplicate_count=len(duplicates),
        rejected_intersection_count=len(rejected),
        degraded=degraded,
        warnings=warnings,
        near_miss_pairs=near_miss,
    )


def _question_block(
    n: int,
    q: Question,
    briefs: list[Brief],
    intersections: list[Intersection],
) -> list[str]:
    inter = next((i for i in intersections if i.id == q.intersection_id), None)
    related = [b for b in briefs if b.id in (q.brief_ids or [])][:2]
    context = q.context
    if not context and related:
        context = related[0].what_is_happening
    if not context and inter:
        context = inter.thesis
    sources = []
    for b in related:
        sources.extend(b.sources)
    src_line = " ".join(f"[source]({u})" for u in sources[:3] if u)
    lines = [
        f"### {n}. {q.text}",
        f"- Lens: {q.lens} · Verticals: {' × '.join(q.verticals) or '—'} · "
        f"Coverage (model guess): **{q.coverage.value}** · Decay: {q.decay_class.value}",
        f"- Context: {context or '—'}",
    ]
    if src_line:
        lines.append(f"- Sources: {src_line}")
    lines.append("")
    return lines


def run_status_from(*, degraded: bool, curated_count: int) -> RunStatus:
    if curated_count == 0:
        return RunStatus.failed
    if degraded:
        return RunStatus.degraded
    return RunStatus.completed
