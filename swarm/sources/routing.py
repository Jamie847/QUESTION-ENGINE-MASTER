from __future__ import annotations

import re
from typing import Any


def contains_keyword(text: str, keyword: str) -> bool:
    blob = text.lower()
    kw = keyword.lower().strip()
    if not kw:
        return False
    if " " in kw or "-" in kw:
        return kw in blob
    # Short tokens must be whole words ("ai" ≠ "attention", "sec" ≠ "security").
    # Longer tokens may take a suffix ("model" → "models").
    if len(kw) <= 3:
        return re.search(rf"\b{re.escape(kw)}\b", blob) is not None
    return re.search(rf"\b{re.escape(kw)}\w*", blob) is not None


def hint_verticals(text: str, vertical_cfgs: list[dict[str, Any]]) -> list[str]:
    hits: list[str] = []
    for v in vertical_cfgs:
        kws = list(v.get("keywords") or []) + list(v.get("hn_keywords") or [])
        if any(contains_keyword(text, str(kw)) for kw in kws):
            hits.append(v["id"])
    return hits


def topic(headline: str, *, words: int = 10) -> str:
    text = re.sub(r"^Wikipedia attention:\s*", "", headline).strip()
    text = text.split(" — ")[0].split(" is colliding")[0]
    parts = text.split()
    cut = " ".join(parts[:words]).rstrip(".,;:")
    return cut or text
