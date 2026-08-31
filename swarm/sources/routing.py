from __future__ import annotations

from typing import Any


def hint_verticals(text: str, vertical_cfgs: list[dict[str, Any]]) -> list[str]:
    blob = text.lower()
    hits: list[str] = []
    for v in vertical_cfgs:
        kws = list(v.get("keywords") or []) + list(v.get("hn_keywords") or [])
        if any(str(kw).lower() in blob for kw in kws):
            hits.append(v["id"])
    return hits
