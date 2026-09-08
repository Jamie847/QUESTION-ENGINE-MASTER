"""Label curator kill reasons so they are a corpus, not page copy."""

from __future__ import annotations

from swarm.models import Question, QuestionStatus

LABELS = (
    "empty_mechanism",
    "generic",
    "seminar",
    "too_short",
    "not_a_question",
    "taste_kill",
    "below_cutoff",
    "curator",
    "other",
)


def label_for(reason: str, explicit: str = "") -> str:
    if explicit and explicit in LABELS:
        return explicit
    low = (reason or "").lower()
    if "mechanism" in low and ("empty" in low or "slot" in low):
        return "empty_mechanism"
    if "generic" in low:
        return "generic"
    if "seminar" in low:
        return "seminar"
    if "too short" in low:
        return "too_short"
    if "not posed" in low or "not a question" in low:
        return "not_a_question"
    if "seeded kill" in low or "too close" in low:
        return "taste_kill"
    if "cutoff" in low or "rank" in low:
        return "below_cutoff"
    if "curator" in low or "not selected" in low:
        return "curator"
    return "other"


def labelled_kills(questions: list[Question]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for q in questions:
        if q.status != QuestionStatus.killed or not q.kill_reason:
            continue
        rows.append((q.id, label_for(q.kill_reason), q.kill_reason))
    return rows
