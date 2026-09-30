from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOICE_PATH = ROOT / "content" / "voice.md"
TASTE_MD = ROOT / "taste" / "seed.md"
# WO-003 names swarm/taste/seed.md; the live file is taste/seed.md.
TASTE_MD_ALIASES = (TASTE_MD, ROOT / "swarm" / "taste" / "seed.md")
TASTE_YAML = ROOT / "taste" / "seed.yaml"

_START = "<!-- OPERATOR_{kind}_START -->"
_END = "<!-- OPERATOR_{kind}_END -->"


def _block(text: str, kind: str) -> str:
    start = _START.format(kind=kind)
    end = _END.format(kind=kind)
    if start not in text or end not in text:
        return ""
    raw = text.split(start, 1)[1].split(end, 1)[0]
    cleaned = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    return cleaned.strip()


def load_voice() -> str:
    if not VOICE_PATH.exists():
        return ""
    return _block(VOICE_PATH.read_text(encoding="utf-8"), "VOICE")


def voice_is_filled() -> bool:
    return bool(load_voice())


def taste_seed_is_filled() -> bool:
    """Operator-authored taste only. The stand-in at data/taste_seed.yaml does not count.

    Ratings that have crossed the keep/kill threshold count as the Operator's seed.
    """
    if TASTE_YAML.exists() and TASTE_YAML.stat().st_size > 0:
        return True
    for path in TASTE_MD_ALIASES:
        if path.exists() and _block(path.read_text(encoding="utf-8"), "TASTE"):
            return True
    from swarm.taste import ratings_seed_ready

    return ratings_seed_ready()
