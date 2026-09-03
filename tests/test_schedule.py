from pathlib import Path

import yaml

from swarm.staleness import NEVER_FIRE_CRON


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
