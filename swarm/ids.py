from __future__ import annotations

import hashlib
import re


def slug(text: str, *, n: int = 10) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]
    head = cleaned[:24].strip("-")
    return f"{head}-{digest}" if head else digest
