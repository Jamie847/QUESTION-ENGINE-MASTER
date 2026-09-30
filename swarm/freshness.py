"""How far back a dated source should look.

Irregular manual runs should not leave a gap, and should not re-read a week
that was already archived. The window is at least 1 day and at most 7.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone


def freshness_window_days(last_archived: datetime | None, now: datetime) -> int:
    if last_archived is None:
        return 1
    if last_archived.tzinfo is None:
        last_archived = last_archived.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    elapsed = now - last_archived
    if elapsed <= timedelta(days=1):
        return 1
    days = math.ceil(elapsed.total_seconds() / 86400)
    return max(1, min(7, days))
