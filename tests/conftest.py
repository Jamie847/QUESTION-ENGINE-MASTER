import os
from pathlib import Path

# Isolate tests from a developer's local digest database.
os.environ.setdefault("DATABASE_URL", "sqlite:///" + str(Path.cwd() / "test_question_engine.db"))
# Existing suite exercises pages and POST /api/run. Production posture
# (empty token fails closed) is covered in tests/test_auth.py.
os.environ.setdefault("ALLOW_UNAUTHENTICATED", "true")

from swarm.settings import get_settings

get_settings.cache_clear()
