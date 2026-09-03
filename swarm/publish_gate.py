"""Publish gate for the Correspondent.

Spec §6 argues against a human approval step for the *digest*: a 10-minute
morning gate is the kind of friction that kills a daily habit. That argument
is correct for a private instrument.

It does not transfer here. A newsletter carries the Operator's name in public.
The digest is for Jamie; the issue is *as* Jamie. Different stakes, different
rule. Do not "fix" this module by adding a publish or send path.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from swarm.orm import DigestRow, QuestionRow, RatingRow
from swarm.voice import taste_seed_is_filled

# Structurally empty. A later reader who adds Substack/email here is
# reversing WO-003. Spec §8's build-but-don't-activate: the path must not exist.
PUBLISH_PATHS: tuple[str, ...] = ()

RATED_WEEKS_REQUIRED = 3


def rated_digest_weeks() -> int:
    """Distinct ISO weeks that have both a digest and at least one Operator rating."""
    from swarm.db import session_scope

    weeks: set[str] = set()
    with session_scope() as session:
        rows = session.execute(
            select(DigestRow.date, RatingRow.id)
            .join(QuestionRow, QuestionRow.run_id == DigestRow.run_id)
            .join(RatingRow, RatingRow.question_id == QuestionRow.id)
        ).all()
        for digest_date, _rating_id in rows:
            try:
                day = date.fromisoformat(str(digest_date))
            except ValueError:
                continue
            iso = day.isocalendar()
            weeks.add(f"{iso.year}-W{iso.week:02d}")
    return len(weeks)


def publish_gate_open() -> bool:
    """True only when both WO-003 §1 conditions hold.

    Even then nothing is published — there is no publish function. This
    flag is for the draft header so the Operator can see whether the gate
    would clear, not a switch that sends mail.
    """
    return taste_seed_is_filled() and rated_digest_weeks() >= RATED_WEEKS_REQUIRED


def gate_reasons() -> list[str]:
    reasons: list[str] = []
    if not taste_seed_is_filled():
        reasons.append(
            "taste seed is still the empty template — Operator must fill "
            "taste/seed.md (or drop taste/seed.yaml)"
        )
    weeks = rated_digest_weeks()
    if weeks < RATED_WEEKS_REQUIRED:
        reasons.append(
            f"{weeks} rated digest week(s) so far; need {RATED_WEEKS_REQUIRED} "
            "before an issue can carry the Operator's name"
        )
    return reasons
