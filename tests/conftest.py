import os
from pathlib import Path

# Isolate tests from a developer's local digest database.
os.environ.setdefault("DATABASE_URL", "sqlite:///" + str(Path.cwd() / "test_question_engine.db"))

from swarm.settings import get_settings

get_settings.cache_clear()
