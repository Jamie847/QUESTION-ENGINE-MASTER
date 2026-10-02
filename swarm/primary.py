"""Primary records and honest source labels. Labels come from the signal."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from swarm.models import Signal

PRIMARY_SOURCES = {
    "federal_register",
    "regulations_gov",
    "arxiv",
    "openalex",
    "nature",
    "science",
    "nejm",
}

PRIMARY_DOMAINS = (
    "federalregister.gov",
    "regulations.gov",
    "arxiv.org",
    "openalex.org",
    "nature.com",
    "science.org",
    "nejm.org",
)

RECORD_RE = re.compile(
    r"\b(rule|docket|filing|paper|regulation|nprm|guidance|"
    r"final rule|proposed rule|notice of proposed|accountability)\b",
    re.I,
)
_TOKEN = re.compile(r"[a-z0-9]{4,}")


def domain_of(url: str) -> str:
    host = (urlparse(url or "").netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def is_primary(*, source: str = "", url: str = "") -> bool:
    if (source or "") in PRIMARY_SOURCES:
        return True
    host = domain_of(url)
    return any(host == d or host.endswith("." + d) for d in PRIMARY_DOMAINS)


def looks_like_record(*texts: str) -> bool:
    return bool(RECORD_RE.search(" ".join(t for t in texts if t)))


def prefer_primary_urls(
    text: str, claimed: list[str], signals: list[Signal]
) -> list[str]:
    """Reorder claimed URLs so a cited primary record leads. Never add a neighbour."""
    allowed = {sig.url for sig in signals if getattr(sig, "url", "")}
    claimed = [u for u in claimed if u and (not allowed or u in allowed)]
    if not looks_like_record(text):
        return claimed
    primaries = [u for u in claimed if is_primary(url=u)]
    rest = [u for u in claimed if u not in primaries]
    return primaries + rest


def _token_overlap(a: str, b: str) -> int:
    ta = set(_TOKEN.findall((a or "").lower()))
    tb = set(_TOKEN.findall((b or "").lower()))
    return len(ta & tb)
