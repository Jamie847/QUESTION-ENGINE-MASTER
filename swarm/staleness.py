from __future__ import annotations

from datetime import date


# Render cron requires a schedule. This expression is 00:00 UTC on 29 February,
# so it only matches a leap-day. It is not a daily job. Manual Trigger Run and
# Controls → Run swarm now are the intended paths.
NEVER_FIRE_CRON = "0 0 29 2 *"


def digest_age_days(digest_date: date | str, *, as_of: date | None = None) -> int:
    if isinstance(digest_date, str):
        digest_date = date.fromisoformat(digest_date)
    as_of = as_of or date.today()
    return max(0, (as_of - digest_date).days)


def is_stale(age_days: int, threshold_days: int) -> bool:
    return age_days > threshold_days


def last_run_label(age_days: int) -> str:
    if age_days == 1:
        return "last run: 1 day ago"
    return f"last run: {age_days} days ago"
