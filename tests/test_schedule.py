from datetime import datetime, timedelta
from pathlib import Path

import yaml

from swarm.staleness import NEVER_FIRE_CRON


def _cron_fields_match(schedule: str, when: datetime) -> bool:
    minute, hour, day, month, _dow = schedule.split()
    checks = (
        (minute, when.minute),
        (hour, when.hour),
        (day, when.day),
        (month, when.month),
    )
    return all(field == "*" or int(field) == value for field, value in checks)


def _fires_in_window(schedule: str, start: datetime, days: int) -> int:
    minute, hour, *_ = schedule.split()
    hits = 0
    for i in range(days):
        day = start + timedelta(days=i)
        when = day.replace(
            hour=0 if hour == "*" else int(hour),
            minute=0 if minute == "*" else int(minute),
            second=0,
            microsecond=0,
        )
        if _cron_fields_match(schedule, when):
            hits += 1
    return hits


def test_blueprint_schedule_does_not_fire_daily():
    """Against `0 10 * * *` this assertion goes red: the job would still
    run every morning. The mechanism that prevents automatic execution is
    the leap-day expression, not a comment."""
    text = Path("render.yaml").read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    cron = next(s for s in doc["services"] if s.get("type") == "cron")
    assert cron["schedule"] == NEVER_FIRE_CRON
    assert cron["schedule"] != "0 10 * * *"
    assert "29 February" in text or "leap-day" in text
    assert cron["startCommand"] == "python -m swarm.run_daily"


def test_leap_day_schedule_does_not_fire_in_the_next_month():
    """This is the 'job does not run' assertion. A daily 10:00 UTC cron
    scores 30 hits in this window and the test goes red."""
    start = datetime(2026, 9, 3, 0, 0)
    assert _fires_in_window(NEVER_FIRE_CRON, start, 30) == 0
    assert _fires_in_window("0 10 * * *", start, 30) == 30
