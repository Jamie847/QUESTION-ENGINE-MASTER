import os
from pathlib import Path

# Isolate tests from a developer's local digest database.
os.environ.setdefault("DATABASE_URL", "sqlite:///" + str(Path.cwd() / "test_question_engine.db"))
# WO-005: dashboard is open. Suite posts to /api/run without a token.
os.environ.setdefault("DASHBOARD_AUTH", "off")
os.environ.setdefault("MAX_RUNS_PER_DAY", "1000")
os.environ.setdefault("RUN_COOLDOWN_SECONDS", "0")

from swarm.settings import get_settings

get_settings.cache_clear()
