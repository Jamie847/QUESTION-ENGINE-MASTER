"""Adapters store a long snippet. The scout prompt trims it."""

from __future__ import annotations

SNIPPET_STORE_CHARS = 2000


def clip_snippet(text: object, limit: int = SNIPPET_STORE_CHARS) -> str:
    if isinstance(text, list):
        text = " ".join(str(part) for part in text)
    cleaned = " ".join(str(text or "").split())
    return cleaned[:limit]
