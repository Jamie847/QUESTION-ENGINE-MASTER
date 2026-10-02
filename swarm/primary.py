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
    """When the brief is about a rule/docket/filing/paper, cite the record first."""
    claimed = [u for u in claimed if u]
    if not looks_like_record(text):
        return claimed
    overlap: list[str] = []
    any_primary: list[str] = []
    for sig in signals:
        if not sig.url or not is_primary(source=sig.source, url=sig.url):
            continue
        any_primary.append(sig.url)
        blob = f"{sig.title} {sig.snippet}"
        if _token_overlap(text, blob) >= 2:
            overlap.append(sig.url)
    lead = overlap or any_primary
    out: list[str] = []
    for url in lead + claimed:
        if url and url not in out:
            out.append(url)
    return out


def _token_overlap(a: str, b: str) -> int:
    ta = set(_TOKEN.findall((a or "").lower()))
    tb = set(_TOKEN.findall((b or "").lower()))
    return len(ta & tb)
