from __future__ import annotations

from pathlib import Path

import yaml

from swarm.models import TasteExample, TasteProfile

ROOT = Path(__file__).resolve().parent.parent
# Prefer a user-authored seed. The bundled file is a stand-in until you
# drop your own voice in taste/seed.yaml.
SEED_CANDIDATES = (
    ROOT / "taste" / "seed.yaml",
    ROOT / "data" / "taste_seed.yaml",
)


def _seed_path() -> Path:
    for path in SEED_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError("no taste seed found")


def load_seed_profile() -> TasteProfile:
    raw = yaml.safe_load(_seed_path().read_text(encoding="utf-8")) or {}
    keeps = [
        TasteExample(stars=row["stars"], question=_clean(row["question"]), why=row.get("why", ""), keep=True)
        for row in raw.get("keeps") or []
    ]
    kills = [
        TasteExample(stars=row["stars"], question=_clean(row["question"]), why=row.get("why", ""), keep=False)
        for row in raw.get("kills") or []
    ]
    return TasteProfile(
        keep_exemplars=keeps,
        kill_exemplars=kills,
        anti_patterns=[
            "implications of",
            "how will X affect",
            "opportunities at the intersection",
            "ethical concerns around",
            "is this the year of",
            "how can nonprofits use",
        ],
        notes=(
            "Seeded voice: specific populations, named mechanisms, "
            "boring infrastructure, falsifiable bets. Kill seminar titles."
        ),
    )


def _clean(text: str) -> str:
    return " ".join(str(text).split())


def profile_for_prompt(profile: TasteProfile, *, keep_n: int = 6, kill_n: int = 5) -> str:
    """Compressed few-shot block. Exemplars rotate later when ratings exist."""
    lines = [profile.notes, "", "KEEP (examples of the user's taste):"]
    for ex in profile.keep_exemplars[:keep_n]:
        lines.append(f"- ({ex.stars}★) {ex.question}")
        if ex.why:
            lines.append(f"  why: {ex.why}")
    lines.append("")
    lines.append("KILL (do not produce these shapes):")
    for ex in profile.kill_exemplars[:kill_n]:
        lines.append(f"- ({ex.stars}★) {ex.question}")
        if ex.why:
            lines.append(f"  why: {ex.why}")
    return "\n".join(lines)
