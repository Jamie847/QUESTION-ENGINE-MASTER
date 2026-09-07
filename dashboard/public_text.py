"""Keep provider billing bodies and request ids off rendered pages."""

from __future__ import annotations

import logging
import re

log = logging.getLogger("dashboard")

_REQUEST_ID = re.compile(r"req_[A-Za-z0-9]+")
_BILLING = (
    "credit balance",
    "too low",
    "insufficient credit",
    "billing",
    "payment",
)


def _looks_like_provider_body(text: str) -> bool:
    low = text.lower()
    if any(marker in low for marker in _BILLING):
        return True
    if "last error:" in low:
        return True
    if "badrequesterror" in low or "error code" in low:
        return True
    if "req_" in text:
        return True
    return False


def public_run_error(err: str) -> str:
    if not err:
        return ""
    log.info("run error withheld from page: %s", err)
    low = err.lower()
    if any(marker in low for marker in _BILLING):
        return "Model call failed."
    return "Run failed."


def public_warning(text: str) -> str:
    if not text:
        return ""
    if _looks_like_provider_body(text):
        log.info("warning withheld from page: %s", text)
        if any(marker in text.lower() for marker in _BILLING):
            return "Model call failed."
        return "A model call failed. See service logs."
    return _REQUEST_ID.sub("req_…", text)


def public_page_text(text: str) -> str:
    """Strip identifiers and billing sentences from a stored blob."""
    if not text:
        return ""
    cleaned = _REQUEST_ID.sub("req_…", text)
    low = cleaned.lower()
    if any(marker in low for marker in _BILLING):
        log.info("billing text withheld from page")
        cleaned = re.sub(
            r"(?i).{0,80}(credit balance|too low|insufficient credit).{0,80}",
            "Model call failed.",
            cleaned,
        )
    return cleaned
