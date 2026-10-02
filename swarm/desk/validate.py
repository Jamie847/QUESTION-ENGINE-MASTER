"""Card honesty: numbers, prospects, rivals, fit. No page fetch."""

from __future__ import annotations

import re
from typing import Any

NUMBER_RE = re.compile(
    r"\$?\d{1,3}(?:,\d{3})+(?:\.\d+)?|\$\d+(?:\.\d+)?|\d+\.\d+|\d{2,}"
)
PROJECTION_RE = re.compile(
    r"\b(tam|sam|som|cagr|market size|billion-dollar|will grow|"
    r"revenue of|projected (?:revenue|sales)|growth rate)\b",
    re.I,
)

NUMERIC_FIELDS = (
    "whats_actually_true",
    "who_has_problem",
    "who_pays",
    "what_they_use_today",
    "why_now",
    "how_it_charges",
    "weekend_test",
    "why_it_might_fail",
    "rivals",
    "fit",
)


def numbers_in(text: str) -> list[str]:
    return NUMBER_RE.findall(text or "")


def _norm(num: str) -> str:
    return re.sub(r"[^\d.]", "", num)


def unsourced_numbers(field: str, evidence: str) -> list[str]:
    have = {_norm(n) for n in numbers_in(evidence) if _norm(n)}
    missing: list[str] = []
    for raw in numbers_in(field):
        key = _norm(raw)
        if key and key not in have and raw not in missing:
            missing.append(raw)
    return missing


def apply_number_rule(
    card: dict[str, Any], evidence: str, *, second_pass: bool = False
) -> tuple[dict[str, Any], bool]:
    """Strip unsourced numbers. A second miss becomes 'not available'."""
    out = dict(card)
    dirty = False
    for key in NUMERIC_FIELDS:
        val = out.get(key)
        if not isinstance(val, str) or not val.strip():
            continue
        if PROJECTION_RE.search(val):
            dirty = True
            out[key] = "not available" if second_pass else PROJECTION_RE.sub("", val).strip()
            val = out[key]
        missing = unsourced_numbers(val, evidence)
        if not missing:
            continue
        dirty = True
        if second_pass:
            out[key] = "not available"
            continue
        cleaned = val
        for num in missing:
            cleaned = cleaned.replace(num, "")
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;.")
        out[key] = cleaned if cleaned else "not available"
    return out, dirty


def filter_prospects(names: list[str], evidence: str) -> list[str]:
    blob = evidence or ""
    kept: list[str] = []
    for name in names:
        label = (name or "").strip()
        if not label:
            continue
        if re.search(re.escape(label), blob, re.I):
            kept.append(label)
    return kept


def rivals_phrase(found: list[str], n_searches: int) -> str:
    names = [n.strip() for n in found if str(n).strip()]
    if names:
        return "; ".join(names)
    return f"none found in {n_searches} searches"


def fit_from_assets(profile: dict[str, str] | None) -> str:
    rows = profile or {}
    if any(str(v).strip() for v in rows.values()):
        return ""
    return "assets profile not written"


def evidence_blob(
    briefs: list[Any],
    searches: list[dict[str, Any]],
) -> str:
    parts: list[str] = []
    for brief in briefs:
        parts.extend(
            [
                str(getattr(brief, "headline", "") or ""),
                str(getattr(brief, "what_is_happening", "") or ""),
                str(getattr(brief, "why_now", "") or ""),
            ]
        )
        for url in getattr(brief, "sources", None) or []:
            parts.append(str(url))
    for hit in searches:
        parts.append(str(hit.get("title") or ""))
        parts.append(str(hit.get("snippet") or ""))
        parts.append(str(hit.get("url") or ""))
        parts.append(str(hit.get("query") or ""))
    return "\n".join(parts)
