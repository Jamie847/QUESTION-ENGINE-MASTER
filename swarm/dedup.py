from __future__ import annotations

import re

from rapidfuzz import fuzz

from swarm.models import NearMissPair, Question, QuestionStatus

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
            q.kill_reason = f"lexical duplicate of {dup_of} ({best:.2f})"
        else:
            kept_norm.append((q.id, q.text))
        out.append(q)
    return out


def _share_kind(a: Question | object, b: Question | object) -> tuple[str, list[str]]:
    va = list(getattr(a, "verticals", None) or [])
    vb = list(getattr(b, "verticals", None) or [])
    shared = sorted(set(va) & set(vb))
    ia = getattr(a, "intersection_id", None)
    ib = getattr(b, "intersection_id", None)
    if ia and ib and ia == ib:
        return "intersection", shared
    if va and sorted(va) == sorted(vb):
        return "intersection", shared
    if shared:
        return "verticals", shared
    return "none", []


def _is_curated(q: object) -> bool:
    status = getattr(q, "status", None)
    if status is None:
        return True
    value = status.value if isinstance(status, QuestionStatus) else str(status)
    return value == QuestionStatus.curated.value


_ACRONYM = re.compile(r"\b[A-Z]{2,}(?:-\d+)?\b")
_PROPER = re.compile(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
_HYPHEN_NUM = re.compile(r"\b[A-Za-z]{2,}-\d+\b")
_TITLE_NUM = re.compile(r"\bTitle\s+[IVXLC]+\b")


def named_terms(text: str) -> set[str]:
    blob = text or ""
    terms = {m.group(0).lower() for m in _ACRONYM.finditer(blob)}
    terms.update(m.group(0).lower() for m in _PROPER.finditer(blob))
    terms.update(m.group(0).lower() for m in _HYPHEN_NUM.finditer(blob))
    terms.update(m.group(0).lower() for m in _TITLE_NUM.finditer(blob))
    return terms


def _urls_for(question: object, briefs_by_id: dict) -> set[str]:
    urls: set[str] = set()
    for bid in getattr(question, "brief_ids", None) or []:
        brief = briefs_by_id.get(bid)
        if brief is None:
            continue
        urls.update(u for u in (getattr(brief, "sources", None) or []) if u)
    return urls


def _share_provenance(
    a: object, b: object, briefs_by_id: dict
) -> tuple[str, list[str]]:
    briefs_a = set(getattr(a, "brief_ids", None) or [])
    briefs_b = set(getattr(b, "brief_ids", None) or [])
    shared_briefs = sorted(briefs_a & briefs_b)
    if shared_briefs:
        return "brief", shared_briefs
    shared_urls = sorted(_urls_for(a, briefs_by_id) & _urls_for(b, briefs_by_id))
    if shared_urls:
        return "url", shared_urls
    ia = getattr(a, "intersection_id", None)
    ib = getattr(b, "intersection_id", None)
    if ia and ib and ia == ib:
        return "intersection", [str(ia)]
    terms = sorted(named_terms(getattr(a, "text", "")) & named_terms(getattr(b, "text", "")))
    if len(terms) >= 2:
        return "terms", terms
    return "none", []


def sample_near_miss_pairs(
    today: list,
    prior: list,
    *,
    n: int = 3,
    briefs_by_id: dict | None = None,
) -> list[NearMissPair]:
    """Surviving questions from adjacent days, ranked so a person can flag paraphrase.

    Lexical silence is not evidence. This sample is the instrument: pairs that
    share an intersection (same vertical set) or at least one vertical, ordered
    by content-token overlap descending. Below the drop threshold on purpose —
    those are the ones the gate let through.
    """
    today_q = [q for q in today if _is_curated(q)]
    prior_q = [q for q in prior if _is_curated(q)]
    if not today_q or not prior_q:
        return []

    if briefs_by_id is not None:
        rank_of = {"brief": 0, "url": 0, "intersection": 1, "terms": 2}
        ranked_p: list[tuple[int, NearMissPair]] = []
        for t in today_q:
            for p in prior_q:
                kind, _shared = _share_provenance(t, p, briefs_by_id)
                if kind == "none":
                    continue
                va = set(getattr(t, "verticals", None) or [])
                vb = set(getattr(p, "verticals", None) or [])
                ranked_p.append(
                    (
                        rank_of[kind],
                        NearMissPair(
                            today_text=t.text,
                            prior_text=p.text,
                            score=round(similarity(t.text, p.text), 3),
                            shared_verticals=sorted(va & vb),
                            share_kind=kind,
                        ),
                    )
                )
        ranked_p.sort(key=lambda row: row[0])
        out: list[NearMissPair] = []
        seen_today: set[str] = set()
        seen_prior: set[str] = set()
        for _rank, pair in ranked_p:
            if pair.today_text in seen_today or pair.prior_text in seen_prior:
                continue
            seen_today.add(pair.today_text)
            seen_prior.add(pair.prior_text)
            out.append(pair)
            if len(out) >= n:
                break
        return out

    ranked: list[tuple[int, float, NearMissPair]] = []
    for t in today_q:
        for p in prior_q:
            kind, shared = _share_kind(t, p)
            score = similarity(t.text, p.text)
            rank = 0 if kind == "intersection" else 1 if kind == "verticals" else 2
            ranked.append(
                (
                    rank,
                    -score,
                    NearMissPair(
                        today_text=t.text,
                        prior_text=p.text,
                        score=round(score, 3),
                        shared_verticals=shared,
                        share_kind=kind,
                    ),
                )
            )
    ranked.sort(key=lambda row: (row[0], row[1]))

    out: list[NearMissPair] = []
    seen_today: set[str] = set()
    seen_prior: set[str] = set()
    for _rank, _neg, pair in ranked:
        if pair.today_text in seen_today or pair.prior_text in seen_prior:
            continue
        seen_today.add(pair.today_text)
        seen_prior.add(pair.prior_text)
        out.append(pair)
        if len(out) >= n:
            break
    return out
