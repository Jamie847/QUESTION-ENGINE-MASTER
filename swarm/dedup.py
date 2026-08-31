from __future__ import annotations

import re

from rapidfuzz import fuzz

from swarm.models import Question, QuestionStatus

_PUNCT = re.compile(r"[^\w\s]")
_SPACE = re.compile(r"\s+")
_STOP = {
    "what", "if", "the", "a", "an", "of", "is", "who", "already", "positioned",
    "for", "reverse", "and", "document", "would", "prove", "it", "stalls",
    "rather", "than", "compounds", "which", "budgets", "headcounts", "are",
    "stranded", "because", "they", "treated", "as", "weather", "profits",
    "story", "around", "mostly", "measurement", "artifact", "still", "true",
    "in", "five", "years", "unglamorous", "institution", "has", "to",
    "absorb", "overflow", "anyone", "staffing", "becomes", "scarce", "keep",
    "moving", "on", "same", "calendar", "job", "that", "looks", "safe",
    "today", "actually", "buffer", "about", "delete", "can", "be", "built",
    "now", "people", "living", "between", "could", "not", "ship", "twelve",
    "months", "ago", "where", "information", "gap", "operators", "touched",
    "vendors", "selling", "last", "year", "workflow", "ignored", "buyer",
    "created", "weekend", "experiment", "find", "them", "consensus", "read",
    "inverted", "how", "does", "this", "with", "from", "when", "will",
}


def normalize(text: str) -> str:
    text = text.lower()
    text = _PUNCT.sub(" ", text)
    text = _SPACE.sub(" ", text).strip()
    return text


def content_tokens(text: str) -> set[str]:
    return {w for w in normalize(text).split() if w not in _STOP and len(w) > 2}


def similarity(a: str, b: str) -> float:
    """Compare the *payload* of two questions, not the shared template words."""
    ua, ub = content_tokens(a), content_tokens(b)
    if len(ua) >= 2 and len(ub) >= 2:
        return len(ua & ub) / len(ua | ub)
    return fuzz.ratio(normalize(a), normalize(b)) / 100.0


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
