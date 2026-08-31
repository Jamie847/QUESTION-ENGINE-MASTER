from __future__ import annotations

import re

from rapidfuzz import fuzz

from swarm.models import Question, QuestionStatus

_PUNCT = re.compile(r"[^\w\s]")
_SPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = text.lower()
    text = _PUNCT.sub(" ", text)
    text = _SPACE.sub(" ", text).strip()
    return text


def similarity(a: str, b: str) -> float:
    return fuzz.token_set_ratio(normalize(a), normalize(b)) / 100.0


def mark_duplicates(
    questions: list[Question],
    prior_texts: list[str],
    *,
    threshold: float = 0.58,
) -> list[Question]:
    """Drop near-duplicates within the batch and against the lookback archive."""
    kept_norm: list[tuple[str, str]] = []
    for prior in prior_texts:
        kept_norm.append(("archive", prior))

    out: list[Question] = []
    for q in questions:
        dup_of: str | None = None
        best = 0.0
        for other_id, other_text in kept_norm:
            score = similarity(q.text, other_text)
            if score >= threshold and score > best:
                best = score
                dup_of = other_id
        if dup_of:
            q.status = QuestionStatus.duplicate
            q.duplicate_of = dup_of
            q.kill_reason = f"semantic duplicate of {dup_of} ({best:.2f})"
        else:
            kept_norm.append((q.id, q.text))
        out.append(q)
    return out
